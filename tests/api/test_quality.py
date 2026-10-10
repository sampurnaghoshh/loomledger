"""Quality: QC queue + rejections (contract), inspections (qc role), DB guards on the reject move."""
from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg.rows import dict_row

from seed import scenario as S
from tests.api.conftest import assert_same_shape, bearer, load_mock, login
from tests.conftest import TEST_URL

pytestmark = pytest.mark.usefixtures("reseed_after_module")
INSPECT = "/api/quality/inspections"


def one(sql: str, params: tuple = ()):
    with psycopg.connect(TEST_URL, row_factory=dict_row, autocommit=True) as conn:
        return conn.execute(sql, params).fetchone()


def on_hand(lot: str, location: str):
    return one("""SELECT lot_on_hand(l.id, loc.id) AS q FROM lot l, location loc
                   WHERE l.code = %s AND loc.code = %s""", (lot, location))["q"]


def moves() -> int:
    return one("SELECT count(*) AS n FROM stock_move")["n"]


@pytest.fixture(scope="module")
def auth(client) -> dict[str, dict]:
    return {role: bearer(login(client, f"{role}@everest.test")) for role in ("owner", "qc", "store", "floor")}


@pytest.fixture(scope="module")
def queue_mock() -> list[dict]:
    return load_mock("quality_queue")


# ---------- reads (run before any write in this module) ----------
@pytest.mark.parametrize("path,mock", [("/api/quality/queue", "quality_queue"),
                                       ("/api/quality/rejections", "quality_rejections")])
def test_reads_match_contract(client, auth, path, mock):
    res = client.get(path, headers=auth["store"])                 # any signed-in role may read
    assert res.status_code == 200
    assert_same_shape(res.json(), load_mock(mock))
    assert res.json() == load_mock(mock)


def test_latest_rejections_are_the_story_day(client, auth):
    res = client.get("/api/quality/latest-rejections", headers=auth["floor"])
    assert res.status_code == 200
    assert res.json() == load_mock("quality_latest_rejections")
    assert res.json()["day"] == S.ANCHOR_DATE.isoformat()                 # the story rolls are rejected on the demo day
    assert {r["lot_code"] for r in res.json()["rejections"]} == set(S.REJECTED_ROLLS)


@pytest.mark.parametrize("path", ["/api/quality/queue", "/api/quality/rejections", "/api/quality/latest-rejections"])
def test_reads_need_token(client, path):
    assert client.get(path).status_code == 401


# ---------- inspections ----------
def test_pass_takes_roll_off_the_queue(client, auth, queue_mock):
    lot = queue_mock[0]["lot_code"]
    before = moves()
    res = client.post(INSPECT, json={"lot_code": lot, "result": "pass"}, headers=auth["qc"])
    assert res.status_code == 201, res.text
    body = res.json()
    assert set(body) == {"inspection_id", "lot_code", "result"} and (body["lot_code"], body["result"]) == (lot, "pass")
    assert lot not in [q["lot_code"] for q in client.get("/api/quality/queue", headers=auth["qc"]).json()]
    assert one("SELECT custody FROM v_roll_custody WHERE lot_code = %s", (lot,))["custody"] == "passed_in_store"
    assert moves() == before                                       # a pass moves nothing


def test_reject_moves_roll_to_reject_bay_and_lists_it(client, auth, queue_mock):
    lot = queue_mock[1]["lot_code"]
    body = {"lot_code": lot, "result": "reject", "defect_type": S.DEFECT, "defect_meters": float(S.ROLL_LENGTH_M),
            "notes": "shade off vs. standard", "idempotency_key": str(uuid.uuid4())}
    res = client.post(INSPECT, json=body, headers=auth["owner"])
    assert res.status_code == 201, res.text
    assert (on_hand(lot, "FG-STORE"), on_hand(lot, "REJECT-BAY")) == (0, S.ROLL_LENGTH_M)

    top = client.get("/api/quality/rejections", headers=auth["qc"]).json()[0]
    inspector = one("SELECT full_name FROM worker WHERE active AND skill IS NULL ORDER BY code LIMIT 1")["full_name"]
    assert (top["lot_code"], top["defect_type"], top["defect_meters"], top["inspector"]) == \
        (lot, S.DEFECT, float(S.ROLL_LENGTH_M), inspector)

    # replay: same key -> the original inspection, no second move
    count = moves()
    again = client.post(INSPECT, json=body, headers=auth["qc"])
    assert again.status_code == 200 and again.json() == res.json()
    assert moves() == count


def test_rework_is_recorded_without_a_move(client, auth, queue_mock):
    lot, before = queue_mock[2]["lot_code"], moves()
    res = client.post(INSPECT, json={"lot_code": lot, "result": "rework", "defect_type": "slub"}, headers=auth["qc"])
    assert res.status_code == 201
    assert one("SELECT custody FROM v_roll_custody WHERE lot_code = %s", (lot,))["custody"] == "rework"
    assert moves() == before


def test_rejecting_a_roll_not_in_fg_store_is_ll002(client, auth):
    """R-1201 is already in the reject bay: the database refuses to move it out of FG-STORE again."""
    res = client.post(INSPECT, json={"lot_code": S.REJECTED_ROLLS[0], "result": "reject", "defect_type": S.DEFECT},
                      headers=auth["qc"])
    assert res.status_code == 422, res.text
    err = res.json()["error"]
    assert (err["code"], err["sqlstate"]) == ("INSUFFICIENT_STOCK", "LL002")
    latest = one("""SELECT count(*) AS n FROM qc_inspection q JOIN lot l ON l.id = q.lot_id WHERE l.code = %s""",
                 (S.REJECTED_ROLLS[0],))["n"]
    assert latest == 1                                              # the inspection rolled back with the move


@pytest.mark.parametrize("body,field", [
    ({"result": "reject"}, "defect_type"), ({"result": "rework", "defect_type": "  "}, "defect_type"),
    ({"result": "pass", "defect_type": "slub"}, "defect_type"), ({"result": "great"}, "result"),
    ({"result": "pass", "lot_code": "R-1212-G"}, "lot_code"), ({"result": "pass", "defect_meters": -1}, "defect_meters"),
    ({"result": "reject", "defect_type": "slub", "idempotency_key": "x"}, "idempotency_key")])
def test_bad_body_is_422(client, auth, body, field):
    res = client.post(INSPECT, json={"lot_code": "R-1101", **body}, headers=auth["qc"])
    assert res.status_code == 422, res.text
    assert field in res.json()["error"]["fields"]


@pytest.mark.parametrize("body,field", [({"lot_code": "R-9999"}, "lot_code"),
                                        ({"lot_code": "R-1101", "inspector_code": "Q-99"}, "inspector_code")])
def test_unknown_reference_is_404(client, auth, body, field):
    res = client.post(INSPECT, json={"result": "pass", **body}, headers=auth["qc"])
    assert res.status_code == 404 and field in res.json()["error"]["fields"]


@pytest.mark.parametrize("role", ["store", "floor"])
def test_wrong_role_is_403(client, auth, role):
    assert client.post(INSPECT, json={"lot_code": "R-1101", "result": "pass"}, headers=auth[role]).status_code == 403


def test_inspect_needs_token(client):
    assert client.post(INSPECT, json={"lot_code": "R-1101", "result": "pass"}).status_code == 401


# ---------- after the recall (keep last) ----------
def test_rejecting_a_quarantined_roll_is_ll001(client, auth):
    one("SELECT apply_recall(id, 'Colour mismatch traced to yarn lot Y-112') FROM lot WHERE code = %s", (S.Y112,))
    awaiting = one("""SELECT s.lot_code FROM recall_scope((SELECT id FROM lot WHERE code = %s)) s
                       WHERE s.custody = 'awaiting_qc' AND s.kind = 'finished' ORDER BY s.lot_code LIMIT 1""",
                   (S.Y112,))["lot_code"]
    res = client.post(INSPECT, json={"lot_code": awaiting, "result": "reject", "defect_type": S.DEFECT},
                      headers=auth["qc"])
    assert res.status_code == 409, res.text
    assert (res.json()["error"]["code"], res.json()["error"]["sqlstate"]) == ("LOT_QUARANTINED", "LL001")
