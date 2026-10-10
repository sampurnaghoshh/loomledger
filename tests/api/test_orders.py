"""Orders, the public buyer page (before + after the recall), and dispatches through the DB guards.

Story order: reads before the recall -> recall applied (pinned to scenario time) -> exact "after"
reads -> dispatch writes. The module reseeds when it ends.
"""
from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg.rows import dict_row

from seed.seed import buyer_token
from tests.api.conftest import apply_story_recall, assert_same_shape, bearer, load_mock, login
from tests.conftest import TEST_URL

pytestmark = pytest.mark.usefixtures("reseed_after_module")
STORY_ORDERS = ("SO-0412", "SO-0419")


def q(sql: str, params: tuple = ()) -> list[dict]:
    with psycopg.connect(TEST_URL, row_factory=dict_row, autocommit=True) as conn:
        return conn.execute(sql, params).fetchall()


def not_found_body() -> dict:
    return {"error": {**{"hint": None, "sqlstate": None, "fields": None}, **load_mock("error_not_found")["error"]}}


def ready_rolls(order: str, n: int, y112: bool = False) -> list[str]:
    """Rolls of an order that passed QC and are in the store (optionally only Y-112 ones)."""
    rows = q("""SELECT c.lot_code FROM v_roll_custody c
                  JOIN reservation rs ON rs.lot_id = c.lot_id JOIN order_line ol ON ol.id = rs.order_line_id
                  JOIN sales_order so ON so.id = ol.order_id
                 WHERE so.code = %s AND c.custody = 'passed_in_store' AND c.kind = 'finished'
                   AND (c.status IN ('quarantined', 'recalled')) = %s
                 ORDER BY c.lot_code LIMIT %s""", (order, y112, n))
    return [r["lot_code"] for r in rows]


def ready_by_batch(order: str) -> dict[str, list[str]]:
    """Passed, in-store, not-held rolls of an order grouped by dye batch (Shade Guard: one batch per dispatch)."""
    rows = q("""SELECT r.code AS batch, c.lot_code FROM v_roll_custody c
                  JOIN lot l ON l.id = c.lot_id JOIN process_run r ON r.id = l.produced_by_run_id
                  JOIN reservation rs ON rs.lot_id = c.lot_id JOIN order_line ol ON ol.id = rs.order_line_id
                  JOIN sales_order so ON so.id = ol.order_id
                 WHERE so.code = %s AND c.custody = 'passed_in_store' AND c.kind = 'finished'
                   AND c.status NOT IN ('quarantined', 'recalled')
                 ORDER BY 1, 2""", (order,))
    batches: dict[str, list[str]] = {}
    for r in rows:
        batches.setdefault(r["batch"], []).append(r["lot_code"])
    return batches


def same_batch_rolls(order: str, n: int) -> list[str]:
    return next(rolls[:n] for rolls in ready_by_batch(order).values() if len(rolls) >= n)


def count(table: str) -> int:
    return q(f"SELECT count(*) AS n FROM {table}")[0]["n"]          # table names are test constants


@pytest.fixture(scope="module")
def auth(client) -> dict[str, dict]:
    return {role: bearer(login(client, f"{role}@everest.test")) for role in ("owner", "store", "qc", "floor")}


# ---------- before the recall ----------
@pytest.mark.parametrize("order", STORY_ORDERS)
def test_track_before_recall_matches_contract(client, order):
    res = client.get(f"/api/track/{buyer_token(order)}")              # public: no Authorization header
    assert res.status_code == 200, res.text
    mock = load_mock(f"track_{order}_before")
    assert_same_shape(res.json(), mock)
    assert res.json() == mock


def test_orders_shape_before_recall(client, auth):
    res = client.get("/api/orders", headers=auth["floor"])           # any signed-in role
    assert res.status_code == 200
    assert_same_shape(res.json(), load_mock("orders"))
    assert all(o["revised_promise_date"] is None for o in res.json())   # nothing is late yet


def test_orders_need_token(client):
    assert client.get("/api/orders").status_code == 401


def test_track_ignores_a_bad_authorization_header(client):
    res = client.get(f"/api/track/{buyer_token('SO-0412')}", headers={"Authorization": "Bearer garbage"})
    assert res.status_code == 200


@pytest.mark.parametrize("token", [str(uuid.uuid4()), "not-a-uuid", "x" * 500, "%27%20OR%201%3D1--"])
def test_track_unknown_or_malformed_token_is_the_same_404(client, token):
    res = client.get(f"/api/track/{token}")
    assert res.status_code == 404
    assert res.json() == not_found_body()                              # same body whatever was wrong


def test_track_expired_link_is_the_same_404(client):
    token = q("""INSERT INTO buyer_link (order_id, expires_at)
                 SELECT id, now() - interval '1 day' FROM sales_order WHERE code = 'SO-0412' RETURNING token""")[0]["token"]
    res = client.get(f"/api/track/{token}")
    assert res.status_code == 404 and res.json() == not_found_body()


# ---------- after the recall (pinned to the scenario's recall time) ----------
@pytest.fixture(scope="module")
def recalled():
    apply_story_recall()


@pytest.mark.parametrize("order", STORY_ORDERS)
def test_track_after_recall_matches_contract(client, recalled, order):
    res = client.get(f"/api/track/{buyer_token(order)}")
    assert res.status_code == 200
    assert res.json() == load_mock(f"track_{order}_after")


def test_orders_after_recall_match_contract(client, auth, recalled):
    res = client.get("/api/orders", headers=auth["owner"])
    assert res.json() == load_mock("orders")                           # the mock was exported post-recall


# ---------- dispatch ----------
def dispatch_body(order: str, lots: list[str], **overrides) -> dict:
    return {"order_code": order, "lot_codes": lots, "vehicle_no": "KA-05-TR-9001",
            "idempotency_key": str(uuid.uuid4()), **overrides}


@pytest.fixture(scope="module")
def shipped(client, auth, recalled) -> dict:
    lots = same_batch_rolls("SO-0412", 2)
    before_dispatched_m = client.get(f"/api/track/{buyer_token('SO-0412')}").json()["progress"]["dispatched_m"]
    body = dispatch_body("SO-0412", lots)
    res = client.post("/api/dispatches", json=body, headers=auth["store"])
    assert res.status_code == 201, res.text
    return {"lots": lots, "body": body, "res": res.json(), "before_dispatched_m": before_dispatched_m}


def test_dispatch_ships_invoices_and_tells_the_buyer(client, shipped):
    lots, res = shipped["lots"], shipped["res"]
    n = q("SELECT count(*) AS n FROM dispatch d JOIN sales_order so ON so.id = d.order_id WHERE so.code = 'SO-0412'")[0]["n"]
    expected_amount = q("""SELECT SUM(l.qty) * ol.unit_price AS amount FROM lot l, order_line ol
                            JOIN sales_order so ON so.id = ol.order_id
                           WHERE l.code = ANY(%s) AND so.code = 'SO-0412' GROUP BY ol.unit_price""", (lots,))[0]["amount"]
    assert res == {"dispatch_code": f"DSP-0412-{n}", "invoice_code": f"INV-0412-{n}", "amount": float(expected_amount)}

    custody = {r["lot_code"]: (r["custody"], r["status"])
               for r in q("SELECT lot_code, custody, status::text AS status FROM v_roll_custody WHERE lot_code = ANY(%s)", (lots,))}
    assert custody == {c: ("at_customer", "dispatched") for c in lots}
    assert q("""SELECT SUM(lot_on_hand(l.id, loc.id)) AS q FROM lot l, location loc
                 WHERE l.code = ANY(%s) AND loc.code = 'FG-STORE'""", (lots,))[0]["q"] == 0

    page = client.get(f"/api/track/{buyer_token('SO-0412')}").json()
    metres = sum(r["qty"] for r in q("SELECT qty FROM lot WHERE code = ANY(%s)", (lots,)))
    assert page["progress"]["dispatched_m"] == shipped["before_dispatched_m"] + float(metres)
    assert page["updates"][0]["message"] == f"Dispatched {len(lots)} rolls ({metres:,.0f} m) on vehicle KA-05-TR-9001."
    assert q("SELECT status::text AS s FROM sales_order WHERE code = 'SO-0412'")[0]["s"] == "partially_dispatched"


def test_dispatch_replay_returns_original(client, auth, shipped):
    dispatches = count("dispatch")
    again = client.post("/api/dispatches", json=shipped["body"], headers=auth["owner"])
    assert again.status_code == 200 and again.json() == shipped["res"]
    assert count("dispatch") == dispatches


def assert_refused(res, status: int, code: str, sqlstate: str | None, before: tuple):
    assert res.status_code == status, res.text
    assert (res.json()["error"]["code"], res.json()["error"]["sqlstate"]) == (code, sqlstate)
    assert (count("dispatch"), count("stock_move"), count("invoice")) == before      # nothing half-written


def test_quarantined_roll_cannot_ship(client, auth, recalled):
    good, held = ready_rolls("SO-0412", 1), ready_rolls("SO-0412", 1, y112=True)
    assert good and held
    before = (count("dispatch"), count("stock_move"), count("invoice"))
    body = dispatch_body("SO-0412", good + held, shade_override_reason="testing the quarantine guard")
    res = client.post("/api/dispatches", json=body, headers=auth["store"])
    assert_refused(res, 409, "LOT_QUARANTINED", "LL001", before)
    assert held[0] in res.json()["error"]["message"]


def test_rejected_roll_cannot_ship(client, auth):
    before = (count("dispatch"), count("stock_move"), count("invoice"))
    res = client.post("/api/dispatches", json=dispatch_body("SO-0412", ["R-1201"]), headers=auth["store"])
    assert_refused(res, 409, "NOT_QC_PASSED", "LL004", before)


def test_roll_of_another_order_cannot_ship(client, auth):
    before = (count("dispatch"), count("stock_move"), count("invoice"))
    res = client.post("/api/dispatches", json=dispatch_body("SO-0419", ready_rolls("SO-0412", 1)), headers=auth["store"])
    assert_refused(res, 422, "NOT_IN_ORDER", "LL005", before)


def test_roll_already_shipped_cannot_ship_again(client, auth, shipped):
    before = (count("dispatch"), count("stock_move"), count("invoice"))
    res = client.post("/api/dispatches", json=dispatch_body("SO-0412", shipped["lots"][:1]), headers=auth["store"])
    assert_refused(res, 409, "ALREADY_DISPATCHED", "23505", before)


# ---------- Shade Guard (008) ----------
def two_batches(order: str) -> tuple[list[str], list[str]]:
    batches = ready_by_batch(order)
    (b1, r1), (b2, r2) = list(batches.items())[:2]
    return [b1, b2], [r1[0], r2[0]]


def test_mixed_dye_batches_are_refused(client, auth, recalled):
    batches, rolls = two_batches("SO-0412")
    before = (count("dispatch"), count("stock_move"), count("invoice"))
    res = client.post("/api/dispatches", json=dispatch_body("SO-0412", rolls), headers=auth["store"])
    assert_refused(res, 409, "SHADE_MISMATCH", "LL006", before)
    assert res.json()["error"]["fields"] == {"batches": ", ".join(sorted(batches))}


def test_shade_override_ships_mixed_batches_and_is_recorded(client, auth, recalled):
    _, rolls = two_batches("SO-0412")
    reason = "Buyer approved mixed dye lots by phone (Ritu, Meridian QA)"
    body = dispatch_body("SO-0412", rolls, shade_override_reason=reason)
    res = client.post("/api/dispatches", json=body, headers=auth["store"])
    assert res.status_code == 201, res.text
    stored = q("SELECT shade_override_reason AS r FROM dispatch WHERE code = %s", (res.json()["dispatch_code"],))
    assert stored == [{"r": reason}]

    dispatches = count("dispatch")
    again = client.post("/api/dispatches", json=body, headers=auth["store"])
    assert again.status_code == 200 and again.json() == res.json()          # replay: the original, nothing new
    assert count("dispatch") == dispatches


@pytest.mark.parametrize("overrides,field", [({"order_code": "SO-9999"}, "order_code"),
                                             ({"lot_codes": ["R-9999"]}, "lot_codes")])
def test_dispatch_unknown_reference_is_404(client, auth, overrides, field):
    res = client.post("/api/dispatches", json=dispatch_body("SO-0412", ["R-1101"], **overrides), headers=auth["store"])
    assert res.status_code == 404 and field in res.json()["error"]["fields"]


@pytest.mark.parametrize("overrides,field", [({"lot_codes": []}, "lot_codes"), ({"lot_codes": ["R-1101", "R-1101"]}, "lot_codes"),
                                             ({"lot_codes": ["Y-112"]}, "lot_codes"), ({"vehicle_no": ""}, "vehicle_no"),
                                             ({"idempotency_key": "x"}, "idempotency_key"),
                                             ({"shade_override_reason": "ok"}, "shade_override_reason")])
def test_dispatch_bad_body_is_422(client, auth, overrides, field):
    res = client.post("/api/dispatches", json=dispatch_body("SO-0412", ["R-1101"], **overrides), headers=auth["store"])
    assert res.status_code == 422 and field in res.json()["error"]["fields"]


@pytest.mark.parametrize("role", ["qc", "floor"])
def test_dispatch_wrong_role_is_403(client, auth, role):
    res = client.post("/api/dispatches", json=dispatch_body("SO-0412", ["R-1101"]), headers=auth[role])
    assert res.status_code == 403


def test_dispatch_needs_token(client):
    assert client.post("/api/dispatches", json=dispatch_body("SO-0412", ["R-1101"])).status_code == 401
