"""Floor endpoints: contract (shape + seeded values), auth, errors, and the state-change write."""
from __future__ import annotations

from datetime import timedelta

import psycopg
import pytest

from seed import scenario as S
from tests.api.conftest import assert_same_shape, bearer, load_mock, login
from tests.conftest import TEST_URL

pytestmark = pytest.mark.usefixtures("reseed_after_module")

ANCHOR = S.ANCHOR_DATE.isoformat()
WINDOW = {"from": (S.ANCHOR_DATE - timedelta(days=30)).isoformat(), "to": ANCHOR}   # the mock's window


@pytest.fixture(scope="module")
def auth(client) -> dict[str, dict]:
    return {role: bearer(login(client, f"{role}@everest.test")) for role in ("owner", "floor", "store", "qc")}


# ---------- reads (run before any write in this module) ----------
def test_machines_match_contract(client, auth):
    res = client.get("/api/floor/machines", headers=auth["qc"])      # any signed-in role may read
    assert res.status_code == 200
    mock = load_mock("floor_machines")
    assert_same_shape(res.json(), mock)
    assert res.json() == mock


def test_output_for_anchor_day_matches_contract(client, auth):
    res = client.get("/api/floor/output", params={"day": ANCHOR}, headers=auth["store"])
    assert res.status_code == 200
    mock = load_mock("floor_output")
    assert_same_shape(res.json(), mock)
    assert res.json() == mock


def test_output_defaults_to_today_ist(client, auth):
    with psycopg.connect(TEST_URL) as conn:
        today = conn.execute("SELECT (now() AT TIME ZONE 'Asia/Kolkata')::date").fetchone()[0]
    res = client.get("/api/floor/output", headers=auth["owner"])
    assert res.status_code == 200
    assert res.json()["day"] == today.isoformat()
    assert_same_shape(res.json(), load_mock("floor_output"))


def test_availability_matches_contract(client, auth):
    res = client.get("/api/floor/availability", params=WINDOW, headers=auth["owner"])
    assert res.status_code == 200
    body, mock = res.json(), load_mock("floor_availability")
    assert_same_shape(body, mock)
    assert body["machines"] == mock["machines"]
    # window echoed in mill time with an offset (the mock's from/to were exported without one)
    assert body["from"] == f"{WINDOW['from']}T00:00:00+05:30" and body["to"] == f"{ANCHOR}T00:00:00+05:30"


def test_availability_default_window_is_30_days(client, auth):
    body = client.get("/api/floor/availability", headers=auth["owner"]).json()
    assert body["from"].endswith("T00:00:00+05:30") and body["to"].endswith("T00:00:00+05:30")
    assert_same_shape(body, load_mock("floor_availability"))


@pytest.mark.parametrize("path", ["/api/floor/machines", "/api/floor/output", "/api/floor/availability"])
def test_reads_need_a_token(client, path):
    res = client.get(path)
    assert res.status_code == 401 and res.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize("path,params,field", [
    ("/api/floor/output", {"day": "yesterday"}, "day"),
    ("/api/floor/availability", {"from": "not-a-date"}, "from"),
    ("/api/floor/availability", {"from": ANCHOR, "to": WINDOW["from"]}, "from"),   # from after to
])
def test_bad_query_is_422(client, auth, path, params, field):
    res = client.get(path, params=params, headers=auth["owner"])
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "VALIDATION_FAILED" and field in res.json()["error"]["fields"]


# ---------- write: machine state ----------
def test_state_change_closes_old_row_and_opens_new(client, auth):
    res = client.post("/api/floor/machines/LOOM-4/state", json={"state": "breakdown", "reason": "Warp beam bearing failure"},
                      headers=auth["floor"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body) == {"machine_code", "state", "started_at"}
    assert (body["machine_code"], body["state"]) == ("LOOM-4", "breakdown")
    assert body["started_at"].endswith("+05:30")

    loom4 = next(m for m in client.get("/api/floor/machines", headers=auth["floor"]).json() if m["code"] == "LOOM-4")
    assert (loom4["state"], loom4["reason"], loom4["state_since"]) == ("breakdown", "Warp beam bearing failure",
                                                                        body["started_at"])
    with psycopg.connect(TEST_URL) as conn:
        open_rows = conn.execute("""SELECT count(*) FROM machine_state_log s JOIN machine m ON m.id = s.machine_id
                                     WHERE m.code = 'LOOM-4' AND s.ended_at IS NULL""").fetchone()[0]
    assert open_rows == 1


def test_owner_can_change_state(client, auth):
    res = client.post("/api/floor/machines/LOOM-4/state", json={"state": "running"}, headers=auth["owner"])
    assert res.status_code == 200 and res.json()["state"] == "running"


def test_state_change_wrong_role_is_403(client, auth):
    res = client.post("/api/floor/machines/LOOM-1/state", json={"state": "running"}, headers=auth["store"])
    assert res.status_code == 403 and res.json()["error"]["code"] == "FORBIDDEN"


def test_state_change_needs_token(client):
    assert client.post("/api/floor/machines/LOOM-1/state", json={"state": "running"}).status_code == 401


def test_state_change_unknown_machine_is_404(client, auth):
    res = client.post("/api/floor/machines/LOOM-99/state", json={"state": "running"}, headers=auth["floor"])
    assert res.status_code == 404 and res.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize("body,field", [({"state": "exploded"}, "state"), ({}, "state"),
                                        ({"state": "idle", "reason": "x" * 201}, "reason")])
def test_state_change_bad_body_is_422(client, auth, body, field):
    res = client.post("/api/floor/machines/LOOM-1/state", json=body, headers=auth["floor"])
    assert res.status_code == 422 and field in res.json()["error"]["fields"]
