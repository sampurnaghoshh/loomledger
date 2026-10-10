"""Monthly P&L + buyer payments (migration 013). Revenue, cash and balances vs the independent
scenario.expected_pnl(); COGS and wages vs lot_cost()/wages(); every error path."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal as D

import psycopg
import pytest
from psycopg.rows import dict_row

from seed import scenario as S
from tests.api.conftest import apply_story_recall, assert_same_shape, bearer, load_mock, login
from tests.conftest import TEST_URL

pytestmark = pytest.mark.usefixtures("reseed_after_module")
PNL, PAY = "/api/finance/pnl", "/api/finance/payments"
MONTH = {"from": S.ANCHOR_DATE.replace(day=1).isoformat(), "to": S.ANCHOR_DATE.isoformat()}


def q(sql: str, params: tuple = ()) -> list[dict]:
    with psycopg.connect(TEST_URL, row_factory=dict_row, autocommit=True) as conn:
        return conn.execute(sql, params).fetchall()


@pytest.fixture(scope="module")
def auth(client) -> dict[str, dict]:
    return {r: bearer(login(client, f"{r}@everest.test")) for r in ("owner", "floor", "accounts", "qc", "store")}


def money(v) -> D:
    return D(str(v)).quantize(D("0.01"))


# ---------- reads (before any write) ----------
def test_pnl_matches_contract_and_the_scenario(client, auth):
    res = client.get(PNL, params=MONTH, headers=auth["accounts"])
    assert res.status_code == 200, res.text
    body, mock = res.json(), load_mock("finance_pnl")
    assert_same_shape(body, mock)
    assert body == mock

    exp = S.expected_pnl(S.ANCHOR_DATE, S.ANCHOR_DATE.replace(day=1), S.ANCHOR_DATE)
    a, c = body["accrual"], body["cash"]
    assert (a["invoices"], a["rolls_invoiced"], money(a["revenue"])) == (exp["invoices"], exp["rolls_invoiced"], exp["revenue"])
    assert money(c["received_from_buyers"]) == exp["received_from_buyers"]
    assert money(c["yarn_bills_paid"]) == exp["yarn_bills_paid"]
    assert {r["buyer_code"]: money(r["outstanding"]) for r in body["receivables"]} == exp["receivables"]
    assert {r["supplier_code"]: money(r["outstanding"]) for r in body["payables"]} == exp["payables"]
    assert money(body["receivables_total"]) == sum(exp["receivables"].values())
    assert money(body["payables_total"]) == sum(exp["payables"].values())
    assert body["recalls"] == []


def test_cogs_is_lot_cost_without_labour_and_labour_is_the_wage_run(client, auth):
    a = client.get(PNL, params=MONTH, headers=auth["owner"]).json()["accrual"]
    rolls = q("""SELECT l.code, rc.material, rc.machine, rc.labour, rc.chemicals
                   FROM invoice i JOIN dispatch_line dl ON dl.dispatch_id = i.dispatch_id
                   JOIN lot l ON l.id = dl.lot_id JOIN v_roll_cost rc ON rc.lot_id = l.id""")
    assert len(rolls) == a["rolls_invoiced"]
    for k in ("material", "machine", "chemicals"):
        assert money(a[k]) == money(sum(r[k] for r in rolls)), k
    assert money(a["labour_in_lot_cost_excluded"]) == money(sum(r["labour"] for r in rolls))
    assert money(a["cost_of_goods_sold"]) == money(a["material"] + a["machine"] + a["chemicals"])

    # independent: the two Y-112 rolls at the buyer, from scenario arithmetic
    labour = S.WEAVER_WAGE_PER_H * S.WEAVE_HOURS + S.DYER_WAGE_PER_H * S.DYE_HOURS / 6
    for r in (r for r in rolls if r["code"] in S.EXPECTED_AT_CUSTOMER):
        assert money(r["material"] + r["machine"] + r["chemicals"]) == money(S.expected_y112_roll_cost(True) - labour)

    run = client.get("/api/workforce/wages", params=MONTH, headers=auth["owner"]).json()
    assert a["wages"] == run["totals"]["gross_wage"] == client.get(PNL, params=MONTH, headers=auth["owner"]).json()["cash"]["wages_paid"]
    assert money(a["profit"]) == money(a["revenue"]) - money(a["cost_of_goods_sold"]) - money(a["wages"])


def test_a_month_without_sales_has_only_costs(client, auth):
    body = client.get(PNL, params={"from": "2026-09-01", "to": "2026-09-30"}, headers=auth["owner"]).json()
    exp = S.expected_pnl(S.ANCHOR_DATE, date(2026, 9, 1), date(2026, 9, 30))
    assert (body["accrual"]["revenue"], body["accrual"]["cost_of_goods_sold"]) == (0, 0)
    assert body["accrual"]["profit"] == -body["accrual"]["wages"]
    assert body["receivables"] == [] and exp["receivables"] == {}
    assert {r["supplier_code"]: money(r["outstanding"]) for r in body["payables"]} == {   # nothing paid yet in Sep
        s: sum((amt for sup, amt in S.expected_bills().values() if sup == s), D(0)) for s in ("SUP-KAV", "SUP-NAR")}


def test_pnl_defaults_to_the_month_of_the_last_working_day(client, auth):
    d = q("SELECT last_working_day((now() AT TIME ZONE 'Asia/Kolkata')::date) AS d")[0]["d"]
    body = client.get(PNL, headers=auth["accounts"]).json()
    assert (body["from"], body["to"]) == (d.replace(day=1).isoformat(), d.isoformat())


def test_pnl_bad_window_is_422(client, auth):
    res = client.get(PNL, params={"from": "2026-10-10", "to": "2026-10-01"}, headers=auth["owner"])
    assert res.status_code == 422 and "from" in res.json()["error"]["fields"]


@pytest.mark.parametrize("role", ["floor", "qc", "store"])
def test_pnl_wrong_role_is_403(client, auth, role):
    assert client.get(PNL, headers=auth[role]).status_code == 403


def test_pnl_needs_token(client):
    assert client.get(PNL).status_code == 401


# ---------- recording a buyer payment ----------
def pay_body(amount, invoice: str = "INV-0412-1", key: str | None = None, method: str = "bank_transfer") -> dict:
    return {"invoice_code": invoice, "amount": amount, "method": method, "idempotency_key": key or str(uuid.uuid4())}


def receivable(client, auth) -> float:
    # as of today: a payment is dated when it is recorded, which can be after the story day (e.g. on a Sunday)
    today = q("SELECT (now() AT TIME ZONE 'Asia/Kolkata')::date AS d")[0]["d"]
    window = MONTH | {"to": max(today, S.ANCHOR_DATE).isoformat()}
    rows = client.get(PNL, params=window, headers=auth["owner"]).json()["receivables"]
    return next((r["outstanding"] for r in rows if r["buyer_code"] == "BUY-MER"), 0)


def test_record_a_payment_and_replay(client, auth):
    before = receivable(client, auth)
    body = pay_body(21000)
    res = client.post(PAY, json=body, headers=auth["accounts"])
    assert res.status_code == 201, res.text
    p = res.json()
    assert (p["invoice_code"], p["amount"], p["method"]) == ("INV-0412-1", 21000, "bank_transfer")
    assert p["outstanding_after"] == before - 21000
    again = client.post(PAY, json=body, headers=auth["accounts"])
    assert again.status_code == 200 and again.json() == p                      # replay: paid once
    assert receivable(client, auth) == before - 21000


def test_overpayment_is_refused_by_the_database(client, auth):
    left = receivable(client, auth)
    count = q("SELECT count(*) AS n FROM payment")[0]["n"]
    res = client.post(PAY, json=pay_body(left + 0.01), headers=auth["owner"])
    assert res.status_code == 422
    err = res.json()["error"]
    assert (err["code"], err["sqlstate"]) == ("OVERPAYMENT", "LL009") and "amount" in err["fields"]
    assert q("SELECT count(*) AS n FROM payment")[0]["n"] == count


def test_paying_off_the_invoice_clears_the_receivable(client, auth):
    left = receivable(client, auth)
    res = client.post(PAY, json=pay_body(left, method="cheque"), headers=auth["accounts"])
    assert res.status_code == 201 and res.json()["outstanding_after"] == 0
    assert receivable(client, auth) == 0
    assert client.post(PAY, json=pay_body(1), headers=auth["accounts"]).json()["error"]["code"] == "OVERPAYMENT"


def test_unknown_invoice_is_404(client, auth):
    res = client.post(PAY, json=pay_body(10, invoice="INV-9999-1"), headers=auth["accounts"])
    assert res.status_code == 404 and "invoice_code" in res.json()["error"]["fields"]


@pytest.mark.parametrize("body", [
    lambda: pay_body(0),
    lambda: pay_body(-50),
    lambda: pay_body(10.005),
    lambda: pay_body(10, method="barter"),
    lambda: pay_body(10, invoice="SO-0412"),
    lambda: pay_body(10, key="short"),
])
def test_bad_payment_body_is_422(client, auth, body):
    res = client.post(PAY, json=body(), headers=auth["accounts"])
    assert res.status_code == 422 and res.json()["error"]["code"] == "VALIDATION_FAILED"


@pytest.mark.parametrize("role", ["store", "floor", "qc"])
def test_payment_wrong_role_is_403(client, auth, role):
    assert client.post(PAY, json=pay_body(10), headers=auth[role]).status_code == 403


def test_payment_needs_token(client):
    assert client.post(PAY, json=pay_body(10)).status_code == 401


# ---------- after the recall (runs last: changes the database) ----------
def test_recall_exposure_is_shown_beside_profit_not_inside_it(client, auth):
    profit_before = client.get(PNL, params=MONTH, headers=auth["owner"]).json()["accrual"]["profit"]
    apply_story_recall()
    body = client.get(PNL, params=MONTH, headers=auth["owner"]).json()
    mock = load_mock("finance_pnl_after_recall")
    assert body["recalls"] == mock["recalls"]
    [r] = body["recalls"]
    m = S.expected_money()
    assert (r["lot_code"], money(r["total_exposure"]), money(r["recall_exposure"])) == \
        (S.Y112, money(m["total_exposure"]), money(m["recall_exposure"]))
    assert body["accrual"]["profit"] == profit_before                           # contingent, not subtracted
