"""Yarn availability (migration 014): low stock, order feasibility, receipts for an order.
Exact values vs the independent scenario.expected_yarn_plan(); every error path; the recall test runs last."""
from __future__ import annotations

import uuid
from decimal import Decimal as D

import psycopg
import pytest
from psycopg.rows import dict_row

from seed import scenario as S
from tests.api.conftest import apply_story_recall, assert_same_shape, bearer, load_mock, login
from tests.conftest import TEST_URL

pytestmark = pytest.mark.usefixtures("reseed_after_module")
LOW, RECEIPTS, MASTERS, STOCK = "/api/inventory/low-stock", "/api/inventory/receipts", "/api/inventory/masters", "/api/inventory/stock"
OPEN = [o.code for o in S.ORDERS if o.code in S.expected_yarn_plan(False)["orders"]]


def check(code: str) -> str:
    return f"/api/orders/{code}/yarn-check"


def q(sql: str, params: tuple = ()) -> list[dict]:
    with psycopg.connect(TEST_URL, row_factory=dict_row, autocommit=True) as conn:
        return conn.execute(sql, params).fetchall()


def kg(v) -> D:
    return D(str(v)).quantize(D("0.001"))


@pytest.fixture(scope="module")
def auth(client) -> dict[str, dict]:
    return {r: bearer(login(client, f"{r}@everest.test")) for r in ("owner", "floor", "accounts", "qc", "store")}


def assert_plan(client, auth, after_recall: bool) -> None:
    exp = S.expected_yarn_plan(after_recall)
    [row] = client.get(LOW, headers=auth["floor"]).json()
    assert row["product_code"] == S.YARN_PRODUCT
    for k in ("on_hand_kg", "quarantined_kg", "committed_kg", "available_kg", "reorder_level_kg"):
        assert kg(row[k]) == kg(exp[k]), k
    assert kg(row["below_reorder_kg"]) == kg(exp["reorder_level_kg"] - exp["available_kg"])
    assert row["open_orders"] == len(exp["orders"])
    for code, e in exp["orders"].items():
        body = client.get(check(code), headers=auth["owner"]).json()
        assert (body["status"], body["due"]) == (e["status"], e["due"].isoformat()), code
        [line] = body["lines"]
        for k in ("covered_m", "unwoven_m", "required_kg", "available_kg", "shortfall_kg"):
            assert kg(line[k]) == kg(e[k]), (code, k)
        ahead = [c for c, o in exp["orders"].items() if (o["due"], c) < (e["due"], code)]
        assert body["orders_ahead"] == sorted(ahead, key=lambda c: (exp["orders"][c]["due"], c))


# ---------- reads, before the recall ----------
def test_low_stock_and_yarn_checks_match_the_scenario(client, auth):
    res = client.get(LOW, headers=auth["store"])
    assert res.status_code == 200, res.text
    assert res.json() == load_mock("inventory_low_stock")
    assert_plan(client, auth, after_recall=False)


def test_a_closed_order_has_nothing_to_check(client, auth):
    closed = next(o.code for o in S.ORDERS if o.code not in OPEN)
    body = client.get(check(closed), headers=auth["owner"]).json()
    assert body == load_mock(f"orders_yarn_check_{closed}")
    assert (body["status"], body["lines"]) == ("closed", [])
    row = next(o for o in client.get("/api/orders", headers=auth["owner"]).json() if o["code"] == closed)
    assert row["yarn_status"] is None


def test_orders_list_carries_the_yarn_status(client, auth):
    exp = S.expected_yarn_plan(False)["orders"]
    for o in client.get("/api/orders", headers=auth["floor"]).json():
        if o["code"] in exp:
            e = exp[o["code"]]
            assert (o["yarn_status"], kg(o["yarn_shortfall_kg"]), kg(o["yarn_required_kg"])) == \
                (e["status"], kg(e["shortfall_kg"]), kg(e["required_kg"])), o["code"]
            assert (o["yarn_short_of"] is not None) == (e["status"] == "short")


def test_unknown_order_is_404(client, auth):
    res = client.get(check("SO-9999"), headers=auth["owner"])
    assert res.status_code == 404 and "order_code" in res.json()["error"]["fields"]


@pytest.mark.parametrize("path", [LOW, check("SO-0419")])
def test_needs_token(client, path):
    assert client.get(path).status_code == 401


# ---------- after the recall (applied once; everything below runs on the recalled database) ----------
def test_quarantined_yarn_is_not_available_after_the_recall(client, auth):
    apply_story_recall()
    assert client.get(LOW, headers=auth["owner"]).json() == load_mock("inventory_low_stock_after_recall")
    assert_plan(client, auth, after_recall=True)
    exp = S.expected_yarn_plan(True)
    assert kg(exp["quarantined_kg"]) == kg(S.expected_money()["quarantined_material_qty"])
    # Y-112's yarn is still physically in the mill, but none of it is usable
    y112 = q("SELECT COALESCE(SUM(qty), 0) AS kg FROM stock_on_hand() WHERE lot_code = %s", (S.Y112,))[0]["kg"]
    assert kg(y112) == kg(exp["quarantined_kg"]) > 0
    before = S.expected_yarn_plan(False)
    assert kg(exp["on_hand_kg"]) == kg(before["on_hand_kg"] - y112)
    # the recall turns a feasible order into a short one
    assert (before["orders"]["SO-0419"]["status"], exp["orders"]["SO-0419"]["status"]) == ("ok", "short")
    for code in OPEN:
        assert client.get(check(code), headers=auth["owner"]).json() == load_mock(f"orders_yarn_check_{code}")


# ---------- gate entry for an order ----------
def receipt(lot: str, order: str | None = None, key: str | None = None) -> dict:
    body = {"supplier_code": "SUP-NAR", "lot_code": lot, "kg": 100, "price_per_kg": 255,
            "idempotency_key": key or str(uuid.uuid4())}
    if order is not None:
        body["order_code"] = order
    return body


def test_masters_list_only_open_orders(client, auth):
    body = client.get(MASTERS, headers=auth["store"]).json()
    assert body == load_mock("inventory_masters")
    assert [o["code"] for o in body["open_orders"]] == sorted(OPEN)


def test_receive_yarn_for_an_order_shows_on_the_grn_and_in_stock(client, auth):
    body = receipt("Y-901", "SO-0419")
    res = client.post(RECEIPTS, json=body, headers=auth["store"])
    assert res.status_code == 201, res.text
    assert res.json()["order_code"] == "SO-0419"
    again = client.post(RECEIPTS, json=body, headers=auth["store"])
    assert again.status_code == 200 and again.json() == res.json()
    rows = client.get(STOCK, headers=auth["owner"]).json()["rows"]
    assert next(r for r in rows if r["lot_code"] == "Y-901")["order_code"] == "SO-0419"
    assert all(r["order_code"] is None for r in rows if r["lot_code"] != "Y-901")
    # new usable yarn raises what is on hand by exactly its weight
    [low] = client.get(LOW, headers=auth["owner"]).json()
    assert kg(low["on_hand_kg"]) == kg(S.expected_yarn_plan(True)["on_hand_kg"] + 100)


def test_receipt_without_an_order_is_general_stock(client, auth):
    res = client.post(RECEIPTS, json=receipt("Y-902"), headers=auth["store"])
    assert res.status_code == 201 and res.json()["order_code"] is None


def test_receipt_for_a_closed_order_is_refused_by_the_database(client, auth):
    closed = next(o.code for o in S.ORDERS if o.code not in OPEN)
    before = q("SELECT count(*) AS n FROM goods_receipt")[0]["n"]
    res = client.post(RECEIPTS, json=receipt("Y-903", closed), headers=auth["store"])
    assert res.status_code == 422
    err = res.json()["error"]
    assert (err["code"], err["sqlstate"]) == ("ORDER_CLOSED", "LL010") and "order_code" in err["fields"]
    assert q("SELECT count(*) AS n FROM goods_receipt")[0]["n"] == before       # one transaction


@pytest.mark.parametrize("order,status,code", [("SO-9999", 404, "NOT_FOUND"), ("0419", 422, "VALIDATION_FAILED")])
def test_receipt_bad_order_code(client, auth, order, status, code):
    res = client.post(RECEIPTS, json=receipt("Y-904", order), headers=auth["store"])
    assert res.status_code == status and res.json()["error"]["code"] == code
