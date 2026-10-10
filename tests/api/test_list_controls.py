"""Paged / searched / sorted / filtered lists (app/listing.py) on the demo seed. Read-only.

Envelope {items, total, page, page_size}; page boundaries; sort both ways; every filter; search (with LIKE
wildcards escaped); unknown sort column -> 422; page_size clamped to 100; roles. The original endpoints are unchanged
(their contract tests still compare them with docs/api-mocks)."""
from __future__ import annotations

import psycopg
import pytest
from psycopg.rows import dict_row

from seed import scenario as S
from tests.api.conftest import bearer, login
from tests.conftest import TEST_URL

ROLLS = "/api/rolls"


def q(sql: str, params: tuple = ()) -> list[dict]:
    with psycopg.connect(TEST_URL, row_factory=dict_row) as conn:
        return conn.execute(sql, params).fetchall()


@pytest.fixture(scope="module")
def auth(client) -> dict[str, dict]:
    return {r: bearer(login(client, f"{r}@everest.test")) for r in ("owner", "floor", "qc", "accounts", "store")}


def get(client, auth, path, role="owner", **params):
    res = client.get(path, params=params, headers=auth[role])
    assert res.status_code == 200, res.text
    return res.json()


def physical_rolls() -> list[str]:
    return sorted(r["lot_code"] for r in q("SELECT lot_code FROM v_roll_custody WHERE custody <> 'consumed'"))


# ---------- envelope + paging
def test_envelope_and_default_page(client, auth):
    body = get(client, auth, ROLLS)
    assert set(body) == {"items", "total", "page", "page_size"}
    assert (body["page"], body["page_size"], body["total"]) == (1, 25, len(physical_rolls()))
    assert [r["code"] for r in body["items"]] == physical_rolls()[:25]


def test_pages_cover_everything_exactly_once(client, auth):
    every, page = [], 1
    while True:
        body = get(client, auth, ROLLS, page=page, page_size=40)
        if not body["items"]:
            break
        every += [r["code"] for r in body["items"]]
        page += 1
    assert every == physical_rolls()
    last = get(client, auth, ROLLS, page=page - 1, page_size=40)
    assert len(last["items"]) == len(every) - 40 * (page - 2)


def test_past_the_last_page_is_empty_but_still_counts(client, auth):
    body = get(client, auth, ROLLS, page=999, page_size=50)
    assert (body["items"], body["total"], body["page"]) == ([], len(physical_rolls()), 999)


def test_page_size_is_capped_at_100(client, auth):
    body = get(client, auth, ROLLS, page_size=500)
    assert body["page_size"] == 100 and len(body["items"]) == min(100, body["total"])


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 0}, {"page": "x"}, {"q": "x" * 101}])
def test_bad_paging_is_422(client, auth, params):
    res = client.get(ROLLS, params=params, headers=auth["owner"])
    assert res.status_code == 422 and res.json()["error"]["code"] == "VALIDATION_FAILED"


# ---------- sort
def test_sort_both_ways(client, auth):
    up = [r["code"] for r in get(client, auth, ROLLS, sort="code", page_size=100)["items"]]
    down = [r["code"] for r in get(client, auth, ROLLS, sort="-code", page_size=100)["items"]]
    assert up == physical_rolls()[:100] and down == sorted(physical_rolls(), reverse=True)[:100]
    by_date = [r["promised_date"] for r in get(client, auth, "/api/orders/list", sort="-promised_date")["items"]]
    assert by_date == sorted(by_date, reverse=True)


@pytest.mark.parametrize("sort", ["nope", "-nope", "code;drop table lot", "custody desc", "1"])
def test_unknown_sort_column_is_422(client, auth, sort):
    res = client.get(ROLLS, params={"sort": sort}, headers=auth["owner"])
    assert res.status_code == 422
    err = res.json()["error"]
    assert err["code"] == "VALIDATION_FAILED" and "sort" in err["fields"]
    assert q("SELECT count(*) AS n FROM lot")[0]["n"] > 0                          # obviously, nothing was dropped


# ---------- filters + search
def test_roll_filters(client, auth):
    shipped = get(client, auth, ROLLS, custody="at_customer", page_size=100)
    assert shipped["total"] == q("SELECT count(*) AS n FROM v_roll_custody WHERE custody = 'at_customer'")[0]["n"]
    assert {r["custody"] for r in shipped["items"]} == {"at_customer"}
    assert set(S.EXPECTED_AT_CUSTOMER) <= {r["code"] for r in shipped["items"]}
    rejected = get(client, auth, ROLLS, qc_result="reject", order_code="SO-0412")
    assert {r["code"] for r in rejected["items"]} == set(S.REJECTED_ROLLS)
    greige = get(client, auth, ROLLS, kind="greige", page_size=100)
    assert greige["items"] and all(r["kind"] == "greige" and r["code"].endswith("-G") for r in greige["items"])
    res = client.get(ROLLS, params={"custody": "lost"}, headers=auth["owner"])
    assert res.status_code == 422                                                     # filters are typed


def test_order_filters_and_search(client, auth):
    meridian = get(client, auth, "/api/orders/list", q="meridian")
    assert [o["code"] for o in meridian["items"]] == ["SO-0412"]
    open_orders = get(client, auth, "/api/orders/list", status="in_production")
    assert {o["status"] for o in open_orders["items"]} == {"in_production"} and open_orders["total"] == 2
    assert get(client, auth, "/api/orders/list", late=True)["total"] == 0               # nothing is late before the recall
    assert get(client, auth, "/api/orders/list", late=False)["total"] == len(S.ORDERS)
    short = get(client, auth, "/api/orders/list", yarn_status="short")
    assert short["items"] and {o["yarn_status"] for o in short["items"]} == {"short"}


def test_search_escapes_like_wildcards(client, auth):
    assert get(client, auth, ROLLS, q="%")["total"] == 0                               # a literal %, not "anything"
    assert get(client, auth, ROLLS, q="r_120")["total"] == 0                          # unescaped, _ would match R-1201
    assert get(client, auth, ROLLS, q="r-120")["total"] == 9                           # R-1201 … R-1209, case-insensitive


def test_quality_lists(client, auth):
    rej = get(client, auth, "/api/quality/rejections/list", defect_type=S.DEFECT)
    assert {r["lot_code"] for r in rej["items"]} == set(S.REJECTED_ROLLS)
    times = [r["inspected_at"] for r in get(client, auth, "/api/quality/rejections/list")["items"]]
    assert times == sorted(times, reverse=True)                                        # newest first by default
    queue = get(client, auth, "/api/quality/queue/list", order_code="SO-0419")
    assert queue["items"] and {r["order_code"] for r in queue["items"]} == {"SO-0419"}


def test_stock_list(client, auth):
    yarn = get(client, auth, "/api/inventory/stock/list", lot_kind="yarn", page_size=100)
    assert yarn["items"] and {r["lot_kind"] for r in yarn["items"]} == {"yarn"}
    assert yarn["total"] == q("SELECT count(*) AS n FROM stock_on_hand() WHERE lot_kind = 'yarn'")[0]["n"]
    qty = [r["qty"] for r in get(client, auth, "/api/inventory/stock/list", sort="-qty")["items"]]
    assert qty == sorted(qty, reverse=True)


def test_invoices_and_workers(client, auth):
    inv = get(client, auth, "/api/finance/invoices", role="accounts")
    assert inv["total"] == len(S.expected_invoices())
    unpaid = get(client, auth, "/api/finance/invoices", role="accounts", unpaid=True)
    assert all(r["outstanding"] > 0 for r in unpaid["items"])
    weavers = get(client, auth, "/api/workforce/workers", role="floor", skill="weaving")
    assert weavers["total"] == 6 and {w["skill"] for w in weavers["items"]} == {"weaving"}
    assert get(client, auth, "/api/workforce/workers", role="floor", q="imran")["items"][0]["full_name"] == "Imran Khan"


@pytest.mark.parametrize("path,role", [("/api/finance/invoices", "floor"), ("/api/workforce/workers", "qc")])
def test_roles(client, auth, path, role):
    assert client.get(path, headers=auth[role]).status_code == 403


def test_needs_token(client):
    assert client.get(ROLLS).status_code == 401
