"""Run progress on the floor (migration 015) and metres still to weave per order. Exact values vs
scenario.expected_run_progress() / expected_yarn_plan(); every error path."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest

from seed import scenario as S
from tests.api.conftest import assert_same_shape, bearer, load_mock, login

pytestmark = pytest.mark.usefixtures("reseed_after_module")
PROGRESS = "/api/floor/progress"
SNAPSHOT = datetime.combine(S.ANCHOR_DATE, S.PROGRESS_SNAPSHOT_AT, ZoneInfo(S.TIMEZONE))


@pytest.fixture(scope="module")
def auth(client) -> dict[str, dict]:
    return {r: bearer(login(client, f"{r}@everest.test")) for r in ("owner", "floor", "store")}


def test_progress_at_the_story_clock_matches_contract_and_scenario(client, auth):
    res = client.get(PROGRESS, params={"at": SNAPSHOT.isoformat()}, headers=auth["floor"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert_same_shape(body, load_mock("floor_progress"))
    assert body == load_mock("floor_progress")
    exp = S.expected_run_progress(D(SNAPSHOT.hour) + D(SNAPSHOT.minute) / 60)
    assert {r["machine_code"] for r in body["runs"]} == set(exp)                 # idle machines are not listed
    for r in body["runs"]:
        e = exp[r["machine_code"]]
        assert r["order_code"] == e["order_code"]
        for k in ("planned_hours", "productive_hours", "progress_pct", "est_done_m", "remaining_hours"):
            assert D(str(r[k])) == e[k], (r["machine_code"], k)
        assert (r["state"], r["paused_hours"], r["over_plan_hours"], r["woven_to_plan_at"]) == ("running", 0, 0, None)
        # snapshot + the unrounded remaining time (planned 50 / 8.33 = 6.0024 h), truncated to the minute
        planned = S.ROLL_LENGTH_M / (S.ROLL_LENGTH_M / S.WEAVE_HOURS).quantize(D("0.01"))
        remaining = planned - (D(SNAPSHOT.hour) + D(SNAPSHOT.minute) / 60 - S.BUSY_FLOOR_START_HOUR)
        end = (SNAPSHOT + timedelta(seconds=float(remaining * 3600))).replace(second=0, microsecond=0)
        assert datetime.fromisoformat(r["expected_end"]) == end


def test_progress_defaults_to_now_and_never_exceeds_100(client, auth):
    body = client.get(PROGRESS, headers=auth["store"]).json()
    at = datetime.fromisoformat(body["at"])
    assert abs((datetime.now(at.tzinfo) - at).total_seconds()) < 60
    for r in body["runs"]:
        assert 0 <= r["progress_pct"] <= 100 and r["est_done_m"] <= r["planned_m"]
        assert (r["remaining_hours"] == 0) or (r["over_plan_hours"] == 0)       # never both
        assert r["woven_to_plan_at"] is None or r["progress_pct"] == 100          # due off the loom only once at plan


def test_before_any_run_started_nothing_is_on_the_floor(client, auth):
    early = SNAPSHOT.replace(hour=S.BUSY_FLOOR_START_HOUR - 1)
    runs = client.get(PROGRESS, params={"at": early.isoformat()}, headers=auth["owner"]).json()["runs"]
    assert [r for r in runs if r["machine_code"] in S.expected_run_progress()] == []


def test_a_breakdown_pauses_the_run(client, auth):
    # live state change through the API (Act 1): the loom stops, its run keeps its progress and has no ETA
    res = client.post("/api/floor/machines/LOOM-4/state", json={"state": "breakdown", "reason": "Warp beam bearing failure"},
                      headers=auth["floor"])
    assert res.status_code == 200, res.text
    row = next(r for r in client.get(PROGRESS, headers=auth["owner"]).json()["runs"] if r["machine_code"] == "LOOM-4")
    assert (row["state"], row["expected_end"]) == ("breakdown", None)


def test_orders_carry_metres_still_to_weave(client, auth):
    exp = S.expected_yarn_plan(False)["orders"]
    for o in client.get("/api/orders", headers=auth["owner"]).json():
        if o["code"] in exp:
            assert D(str(o["to_weave_m"])) == exp[o["code"]]["unwoven_m"], o["code"]
        else:
            assert o["to_weave_m"] is None                                       # closed order


def test_bad_time_is_422(client, auth):
    res = client.get(PROGRESS, params={"at": "half past nine"}, headers=auth["owner"])
    assert res.status_code == 422 and res.json()["error"]["code"] == "VALIDATION_FAILED"


def test_needs_token(client):
    assert client.get(PROGRESS).status_code == 401
