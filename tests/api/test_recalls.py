"""Recall (Acts 3–4) through the API, in story order:
preview (= mock, money = scenario.py's independent model) -> apply -> apply again (same recall) ->
Y-112 refused by PostgreSQL -> preview after (pinned time) = recall_applied.json."""
from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import psycopg
import pytest

from seed import scenario as S
from tests.api.conftest import assert_same_shape, bearer, load_mock, login
from tests.conftest import TEST_URL

pytestmark = pytest.mark.usefixtures("reseed_after_module")
PREVIEW, APPLY = "/api/recalls/preview", "/api/recalls"
REASON = "Colour mismatch traced to yarn lot Y-112"


def count(table: str) -> int:
    with psycopg.connect(TEST_URL) as conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]     # table names are test constants


@pytest.fixture(scope="module")
def auth(client) -> dict[str, dict]:
    return {role: bearer(login(client, f"{role}@everest.test")) for role in ("owner", "qc", "store", "floor")}


# ---------- before applying ----------
def test_preview_matches_contract(client, auth):
    res = client.get(PREVIEW, params={"lot_code": S.Y112}, headers=auth["store"])      # any signed-in role
    assert res.status_code == 200, res.text
    mock = load_mock("recall_preview")
    assert_same_shape(res.json(), mock)
    assert res.json() == mock


def test_preview_impact_equals_the_independent_model(client, auth):
    body = client.get(PREVIEW, params={"lot_code": S.Y112}, headers=auth["qc"]).json()
    impact = body["impact"]
    for key, value in S.EXPECTED_SCOPE.items():
        assert impact[key] == value, key
    assert impact["remake_m"] == float(S.expected_remake_m())
    assert impact["throughput_m_per_day"] == float(S.expected_throughput())
    assert impact["additional_delay_days"] == S.expected_delay_days()
    money = S.expected_money()
    for key in ("cost_already_incurred", "cost_in_factory", "cost_wip", "cost_at_customer", "recall_exposure",
                "quarantined_material_qty", "quarantined_material_value", "total_exposure"):
        assert impact[key] == float(money[key].quantize(S.D("0.01"))), key

    expected_orders = S.expected_order_impact()
    assert [o["order_code"] for o in body["orders"]] == list(expected_orders)
    for o in body["orders"]:
        e = expected_orders[o["order_code"]]
        assert (o["affected_rolls"], o["remake_m"], o["delay_days"]) == (e["rolls"], float(e["remake_m"]), e["delay_days"])
        assert (o["promised_date"], o["revised_promise_date"]) == (e["promised"].isoformat(), e["revised"].isoformat())
    assert body["calculation"]["additional_delay_days"] == S.expected_delay_days()


# ---------- apply ----------
@pytest.fixture(scope="module")
def applied(client, auth) -> dict:
    moves = count("stock_move")
    res = client.post(APPLY, json={"lot_code": S.Y112, "reason": REASON}, headers=auth["qc"])
    assert res.status_code == 201, res.text
    return {"res": res.json(), "moves_after_first": count("stock_move"), "moves_before": moves}


def test_apply_returns_the_applied_recall(applied):
    body, mock = applied["res"], load_mock("recall_applied")
    assert_same_shape(body, mock)
    assert body["applied"] is True and body["recall_code"] == mock["recall_code"]
    assert {k: v for k, v in body.items() if k != "applied_at"} == {k: v for k, v in mock.items() if k != "applied_at"}
    assert applied["moves_after_first"] > applied["moves_before"]          # stock was physically quarantined


def test_apply_again_is_the_same_recall(client, auth, applied):
    again = client.post(APPLY, json={"lot_code": S.Y112, "reason": "pressed twice"}, headers=auth["owner"])
    assert again.status_code == 200
    assert again.json() == applied["res"]                                  # same code, same time, same numbers
    assert count("stock_move") == applied["moves_after_first"] and count("recall") == 1


def test_after_apply_postgres_refuses_y112(client, auth, applied):
    res = client.post("/api/production/weaving-runs", headers=auth["floor"], json={
        "machine_code": "LOOM-2", "yarn_lot_code": S.Y112, "product_code": "GRG-TWL",
        "meters_planned": float(S.ROLL_LENGTH_M), "idempotency_key": str(uuid.uuid4())})
    assert res.status_code == 409
    assert res.json()["error"] == {**load_mock("error_lot_quarantined")["error"], "fields": None}


def test_preview_after_apply_matches_contract(client, auth, applied):
    recall_at = datetime.combine(S.ANCHOR_DATE, S.RECALL_APPLIED_AT, ZoneInfo(S.TIMEZONE))
    with psycopg.connect(TEST_URL) as conn, conn.transaction():               # pin the time as the export does
        conn.execute("UPDATE recall SET initiated_at = %s", (recall_at,))
    res = client.get(PREVIEW, params={"lot_code": S.Y112}, headers=auth["qc"])
    assert res.json() == load_mock("recall_applied")


def test_impact_is_unchanged_by_applying(client, auth, applied):
    after = client.get(PREVIEW, params={"lot_code": S.Y112}, headers=auth["qc"]).json()
    assert after["impact"] == load_mock("recall_preview")["impact"]       # custody comes from facts, not status


# ---------- errors ----------
def test_unknown_lot_is_404(client, auth):
    assert client.get(PREVIEW, params={"lot_code": "Y-999"}, headers=auth["qc"]).status_code == 404
    res = client.post(APPLY, json={"lot_code": "Y-999", "reason": REASON}, headers=auth["qc"])
    assert res.status_code == 404 and res.json()["error"]["fields"] == {"lot_code": "not found"}


@pytest.mark.parametrize("body,field", [({"lot_code": S.Y112}, "reason"), ({"lot_code": S.Y112, "reason": "x"}, "reason"),
                                        ({"reason": REASON}, "lot_code")])
def test_apply_bad_body_is_422(client, auth, body, field):
    res = client.post(APPLY, json=body, headers=auth["qc"])
    assert res.status_code == 422 and field in res.json()["error"]["fields"]


def test_preview_needs_lot_code(client, auth):
    res = client.get(PREVIEW, headers=auth["qc"])
    assert res.status_code == 422 and "lot_code" in res.json()["error"]["fields"]


@pytest.mark.parametrize("role", ["store", "floor"])
def test_apply_wrong_role_is_403(client, auth, role):
    assert client.post(APPLY, json={"lot_code": S.Y112, "reason": REASON}, headers=auth[role]).status_code == 403


def test_needs_token(client):
    assert client.get(PREVIEW, params={"lot_code": S.Y112}).status_code == 401
    assert client.post(APPLY, json={"lot_code": S.Y112, "reason": REASON}).status_code == 401
