"""Role-based access (migration 017): the matrix lives in the database; every protected route asks it.

Expected grants below are written independently from CLAUDE.md §6 (store -> receipts + dispatch; floor supervisor ->
floor / production / register; qc -> inspections, recalls, alerts, validation log; accounts -> finance + wages;
owner -> everything). Users & roles: last active owner (LL011), no self-deactivation (LL012), a deactivated user
can't sign in and their existing token stops working, every change is audited with the acting owner."""
from __future__ import annotations

import psycopg
import pytest
from psycopg.rows import dict_row

from tests.api.conftest import bearer, login
from tests.conftest import TEST_URL

pytestmark = pytest.mark.usefixtures("reseed_after_module")
ROLES = ("owner", "store", "floor_supervisor", "qc", "accounts")
EMAIL = {"owner": "owner", "store": "store", "floor_supervisor": "floor", "qc": "qc", "accounts": "accounts"}
GRANTS = {
    "store": {"inventory.receive", "orders.dispatch"},
    "floor_supervisor": {"floor.change_state", "production.start_run", "workforce.register"},
    "qc": {"quality.inspect", "recalls.apply", "alerts.listen", "validation_log.view"},
    "accounts": {"finance.access", "workforce.wages"},
}
# (method, path, permission): forbidden roles get 403 before the body is even read; allowed roles get past it
PROTECTED = [
    ("POST", "/api/floor/machines/LOOM-1/state", "floor.change_state"),
    ("POST", "/api/production/weaving-runs", "production.start_run"),
    ("POST", "/api/inventory/receipts", "inventory.receive"),
    ("GET", "/api/inventory/masters", "inventory.receive"),
    ("POST", "/api/dispatches", "orders.dispatch"),
    ("POST", "/api/quality/inspections", "quality.inspect"),
    ("POST", "/api/recalls", "recalls.apply"),
    ("GET", "/api/finance/pnl", "finance.access"),
    ("GET", "/api/finance/invoices", "finance.access"),
    ("GET", "/api/workforce/workers", "workforce.register"),
    ("GET", "/api/workforce/wages", "workforce.wages"),
    ("GET", "/api/users", "users.manage"),
]


def q(sql: str, params: tuple = ()) -> list[dict]:
    with psycopg.connect(TEST_URL, row_factory=dict_row, autocommit=True) as conn:
        return conn.execute(sql, params).fetchall()


def run(sql: str, params: tuple = ()) -> None:
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        conn.execute(sql, params)


def user_id(role: str) -> int:
    return q("SELECT id FROM app_user WHERE email = %s", (f"{EMAIL[role]}@everest.test",))[0]["id"]


@pytest.fixture(scope="module")
def auth(client) -> dict[str, dict]:
    return {r: bearer(login(client, f"{EMAIL[r]}@everest.test")) for r in ROLES}


# ---------- the matrix (read-only tests first)
def test_permissions_matrix_and_mine(client, auth):
    for role in ROLES:
        body = client.get("/api/auth/permissions", headers=auth[role]).json()
        assert body["roles"] == list(ROLES)
        codes = {p["code"] for p in body["permissions"]}
        expected = codes if role == "owner" else GRANTS[role]
        assert (body["me"]["role"], set(body["me"]["permissions"])) == (role, expected), role
        assert all(p["description"] and p["area"] for p in body["permissions"])
    assert client.get("/api/auth/permissions").status_code == 401


@pytest.mark.parametrize("method,path,permission", PROTECTED)
def test_every_protected_route_asks_the_matrix(client, auth, method, path, permission):
    for role in ROLES:
        res = client.request(method, path, json={} if method == "POST" else None, headers=auth[role])
        allowed = role == "owner" or permission in GRANTS[role]
        assert (res.status_code != 403) == allowed, (role, path, res.status_code)
        if not allowed:
            assert res.json()["error"]["code"] == "FORBIDDEN"


def test_the_matrix_really_drives_access(client, auth):
    """Revoke a grant in the DATABASE and the API follows immediately; restore it."""
    run("DELETE FROM role_permission WHERE role = 'accounts' AND permission = 'finance.access'")
    try:
        assert client.get("/api/finance/pnl", headers=auth["accounts"]).status_code == 403
    finally:
        run("INSERT INTO role_permission (role, permission) VALUES ('accounts', 'finance.access')")
    assert client.get("/api/finance/pnl", headers=auth["accounts"]).status_code == 200


def test_users_list_is_paged_and_searchable(client, auth):
    body = client.get("/api/users", params={"q": "everest", "sort": "-email"}, headers=auth["owner"]).json()
    assert body["total"] == 5 and [u["email"] for u in body["items"]] == sorted((u["email"] for u in body["items"]), reverse=True)
    assert {u["role"] for u in client.get("/api/users", params={"role": "qc"}, headers=auth["owner"]).json()["items"]} == {"qc"}


# ---------- changing access (writes)
def test_deactivated_user_cannot_sign_in_and_their_token_stops_working(client, auth):
    store = user_id("store")
    assert client.get("/api/orders", headers=auth["store"]).status_code == 200
    res = client.patch(f"/api/users/{store}", json={"active": False}, headers=auth["owner"])
    assert res.status_code == 200 and res.json()["active"] is False
    assert client.get("/api/orders", headers=auth["store"]).status_code == 401                 # existing token refused
    bad = client.post("/api/auth/login", json={"email": "store@everest.test", "password": "demo1234"})
    assert bad.status_code == 401
    audit = q("""SELECT changed_by, old_data->>'active' AS was, new_data->>'active' AS now FROM audit_log
                  WHERE table_name = 'app_user' AND row_id = %s ORDER BY id DESC LIMIT 1""", (store,))[0]
    assert audit == {"changed_by": "owner@everest.test", "was": "true", "now": "false"}
    assert client.patch(f"/api/users/{store}", json={"active": True}, headers=auth["owner"]).status_code == 200
    assert login(client, "store@everest.test")


def test_you_cannot_deactivate_yourself(client, auth):
    res = client.patch(f"/api/users/{user_id('owner')}", json={"active": False}, headers=auth["owner"])
    assert res.status_code == 409
    err = res.json()["error"]
    assert (err["code"], err["sqlstate"]) == ("SELF_DEACTIVATION", "LL012") and "active" in err["fields"]


def test_the_last_active_owner_is_guarded(client, auth):
    owner, qc = user_id("owner"), user_id("qc")
    res = client.patch(f"/api/users/{owner}", json={"role": "qc"}, headers=auth["owner"])
    assert res.status_code == 409 and res.json()["error"]["code"] == "LAST_OWNER"
    # with a second owner it is allowed; then the guard protects the new one
    assert client.patch(f"/api/users/{qc}", json={"role": "owner"}, headers=auth["owner"]).status_code == 200
    assert client.patch(f"/api/users/{owner}", json={"role": "accounts"}, headers=auth["owner"]).status_code == 200
    qc_token = bearer(login(client, "qc@everest.test"))
    last = client.patch(f"/api/users/{qc}", json={"active": False}, headers=qc_token)
    assert last.status_code == 409                                    # self-deactivation is checked first
    assert client.patch(f"/api/users/{owner}", json={"role": "owner"}, headers=qc_token).status_code == 200
    assert client.patch(f"/api/users/{qc}", json={"role": "qc"}, headers=auth["owner"]).status_code == 200
    # and directly in the database, whatever the client
    with pytest.raises(psycopg.Error) as e:
        run("UPDATE app_user SET active = false WHERE role = 'owner'")
    assert e.value.sqlstate == "LL011"


@pytest.mark.parametrize("body", [{}, {"role": "admin"}, {"active": "maybe"}, {"role": "qc", "email": "x@y.z"}])
def test_bad_change_is_422(client, auth, body):
    res = client.patch(f"/api/users/{user_id('qc')}", json=body, headers=auth["owner"])
    assert res.status_code == 422 and res.json()["error"]["code"] == "VALIDATION_FAILED"


def test_unknown_user_is_404(client, auth):
    assert client.patch("/api/users/999999", json={"active": True}, headers=auth["owner"]).status_code == 404
