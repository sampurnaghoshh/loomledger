"""Inventory endpoints: stock now / time travel (contract), yarn receipts (idempotent write), auth, errors.

Receipts move stock from the supplier location into a fresh, active lot, so the ledger guards
LL001 (quarantine) and LL002 (stock) cannot trigger here — those are covered where stock leaves a
location (tests/test_ledger_invariants.py, and the production endpoints).
"""
from __future__ import annotations

import uuid

import pytest

from tests.api.conftest import assert_same_shape, bearer, load_mock, login

pytestmark = pytest.mark.usefixtures("reseed_after_module")


@pytest.fixture(scope="module")
def auth(client) -> dict[str, dict]:
    return {role: bearer(login(client, f"{role}@everest.test")) for role in ("owner", "store", "qc")}


def receipt(**overrides) -> dict:
    body = {"supplier_code": "SUP-KAV", "lot_code": "Y-901", "kg": 150.5, "price_per_kg": 261.0,
            "vehicle_no": "KA-01-AB-9999", "challan_no": "CH-9001", "idempotency_key": str(uuid.uuid4())}
    return {**body, **overrides}


# ---------- reads (run before any write in this module) ----------
def test_stock_now_matches_contract(client, auth):
    res = client.get("/api/inventory/stock", headers=auth["qc"])
    assert res.status_code == 200
    mock = load_mock("inventory_stock_now")
    assert_same_shape(res.json(), mock)
    assert res.json() == mock


def test_stock_time_travel_matches_contract(client, auth):
    mock = load_mock("inventory_stock_as_of")
    res = client.get("/api/inventory/stock", params={"as_of": mock["as_of"]}, headers=auth["owner"])
    assert res.status_code == 200
    assert_same_shape(res.json(), mock)
    assert res.json() == mock


def test_stock_naive_as_of_is_mill_time(client, auth):
    mock = load_mock("inventory_stock_as_of")
    naive = mock["as_of"].removesuffix("+05:30")
    assert client.get("/api/inventory/stock", params={"as_of": naive}, headers=auth["owner"]).json() == mock


def test_stock_bad_as_of_is_422(client, auth):
    res = client.get("/api/inventory/stock", params={"as_of": "last tuesday"}, headers=auth["owner"])
    assert res.status_code == 422 and "as_of" in res.json()["error"]["fields"]


def test_stock_needs_token(client):
    assert client.get("/api/inventory/stock").status_code == 401


# ---------- write: receipts ----------
def test_receipt_creates_lot_in_yarn_store(client, auth):
    body = receipt()
    res = client.post("/api/inventory/receipts", json=body, headers=auth["store"])
    assert res.status_code == 201, res.text
    assert res.json() == {"receipt_code": "GRN-Y-901", "lot_code": "Y-901", "kg": 150.5, "location": "YARN-STORE"}

    rows = client.get("/api/inventory/stock", headers=auth["store"]).json()["rows"]
    assert [r for r in rows if r["lot_code"] == "Y-901"] == [
        {"location_code": "YARN-STORE", "lot_code": "Y-901", "lot_kind": "yarn", "product_code": "YRN-C40",
         "qty": 150.5, "uom": "kg"}]


def test_receipt_replay_returns_original(client, auth):
    body = receipt(lot_code="Y-902")
    first = client.post("/api/inventory/receipts", json=body, headers=auth["store"])
    again = client.post("/api/inventory/receipts", json=body, headers=auth["store"])
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json() == first.json()
    rows = client.get("/api/inventory/stock", headers=auth["store"]).json()["rows"]
    assert sum(r["qty"] for r in rows if r["lot_code"] == "Y-902") == body["kg"]     # received once


def test_owner_can_receive(client, auth):
    assert client.post("/api/inventory/receipts", json=receipt(lot_code="Y-903"), headers=auth["owner"]).status_code == 201


def test_receipt_wrong_role_is_403(client, auth):
    res = client.post("/api/inventory/receipts", json=receipt(lot_code="Y-904"), headers=auth["qc"])
    assert res.status_code == 403 and res.json()["error"]["code"] == "FORBIDDEN"


def test_receipt_needs_token(client):
    assert client.post("/api/inventory/receipts", json=receipt(lot_code="Y-905")).status_code == 401


@pytest.mark.parametrize("overrides,field", [({"supplier_code": "SUP-NOPE"}, "supplier_code"),
                                             ({"supplier_code": "BUY-MER"}, "supplier_code"),   # a buyer, not a supplier
                                             ({"product_code": "FIN-TWL-NVY"}, "product_code")])  # not yarn
def test_receipt_unknown_reference_is_404(client, auth, overrides, field):
    res = client.post("/api/inventory/receipts", json=receipt(lot_code="Y-906", **overrides), headers=auth["store"])
    assert res.status_code == 404, res.text
    assert res.json()["error"]["code"] == "NOT_FOUND" and field in res.json()["error"]["fields"]


def test_receipt_existing_lot_code_is_422(client, auth):
    res = client.post("/api/inventory/receipts", json=receipt(lot_code="Y-112"), headers=auth["store"])
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "VALIDATION_FAILED" and res.json()["error"]["fields"] == {"lot_code": "already exists"}


@pytest.mark.parametrize("overrides,field", [({"kg": 0}, "kg"), ({"kg": -5}, "kg"), ({"price_per_kg": 0}, "price_per_kg"),
                                             ({"lot_code": "R-1201"}, "lot_code"), ({"lot_code": "Y-1"}, "lot_code"),
                                             ({"idempotency_key": "x"}, "idempotency_key")])
def test_receipt_bad_body_is_422(client, auth, overrides, field):
    res = client.post("/api/inventory/receipts", json=receipt(**overrides), headers=auth["store"])
    assert res.status_code == 422 and field in res.json()["error"]["fields"]
