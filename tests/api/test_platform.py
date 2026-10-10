"""Platform: health, auth, roles, error envelope, SQLSTATE mapping."""
from __future__ import annotations

import psycopg
import pytest

from app.errors import is_idempotency_replay, map_db_error
from tests.api.conftest import bearer, load_mock, login
from tests.conftest import TEST_URL

ENVELOPE_KEYS = {"code", "message", "hint", "sqlstate", "fields"}


def assert_error(res, status: int, code: str) -> dict:
    assert res.status_code == status, res.text
    body = res.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == ENVELOPE_KEYS
    assert body["error"]["code"] == code
    return body["error"]


# ---------- health + middleware ----------
def test_health_ok(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok" and res.json()["db"] == "ok"


def test_request_id_generated_and_echoed(client):
    assert len(client.get("/api/health").headers["X-Request-ID"]) == 32
    assert client.get("/api/health", headers={"X-Request-ID": "abc-123"}).headers["X-Request-ID"] == "abc-123"
    # unsafe ids are replaced, not echoed
    assert client.get("/api/health", headers={"X-Request-ID": "<script>"}).headers["X-Request-ID"] != "<script>"


def test_cors_allows_frontend_origin(client):
    res = client.options("/api/auth/login", headers={"Origin": "http://localhost:5173",
                                                     "Access-Control-Request-Method": "POST"})
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"


# ---------- login ----------
def test_login_success_matches_mock_shape(client):
    res = client.post("/api/auth/login", json={"email": "owner@everest.test", "password": "demo1234"})
    assert res.status_code == 200, res.text
    body, mock = res.json(), load_mock("auth_login")
    assert set(body) == set(mock)
    assert set(body["user"]) == set(mock["user"])
    assert body["user"] == mock["user"]                      # seeded owner is the mock's owner
    assert isinstance(body["token"], str) and len(body["token"]) > 20


def test_login_email_is_case_insensitive(client):
    res = client.post("/api/auth/login", json={"email": "QC@Everest.test", "password": "demo1234"})
    assert res.status_code == 200
    assert res.json()["user"]["role"] == "qc"


@pytest.mark.parametrize("email,password", [("owner@everest.test", "wrong"), ("nobody@everest.test", "demo1234")])
def test_login_bad_credentials(client, email, password):
    err = assert_error(client.post("/api/auth/login", json={"email": email, "password": password}),
                       401, "INVALID_CREDENTIALS")
    assert "password" in err["message"].lower()


# ---------- tokens + roles ----------
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer garbage.token.here"},
                                     {"Authorization": "Basic abc"}, {"Authorization": "Bearer "}])
def test_missing_or_garbage_token_is_401(client, headers):
    assert_error(client.get("/api/_test/qc-only", headers=headers), 401, "UNAUTHENTICATED")


def test_expired_token_is_401(client, monkeypatch):
    import app.auth as auth
    token = auth.issue_token(1)
    monkeypatch.setattr(auth.get_settings(), "TOKEN_TTL_HOURS", -1)
    assert_error(client.get("/api/_test/qc-only", headers=bearer(token)), 401, "UNAUTHENTICATED")


def test_token_signed_with_other_key_is_401(client):
    from itsdangerous import URLSafeTimedSerializer
    forged = URLSafeTimedSerializer("not-our-key", salt="loomledger-auth").dumps({"uid": 1})
    assert_error(client.get("/api/_test/qc-only", headers=bearer(forged)), 401, "UNAUTHENTICATED")


def test_require_role_allows_listed_role_and_owner(client, owner_token):
    qc = login(client, "qc@everest.test")
    assert client.get("/api/_test/qc-only", headers=bearer(qc)).json() == {"role": "qc"}
    assert client.get("/api/_test/qc-only", headers=bearer(owner_token)).json() == {"role": "owner"}


def test_require_role_wrong_role_is_403(client):
    store = login(client, "store@everest.test")
    assert_error(client.get("/api/_test/qc-only", headers=bearer(store)), 403, "FORBIDDEN")


# ---------- envelope for non-DB errors ----------
def test_validation_error_is_422_with_fields(client):
    err = assert_error(client.post("/api/_test/validate", json={"kg": -5, "lot_code": "X-1"}),
                       422, "VALIDATION_FAILED")
    assert set(err["fields"]) == {"kg", "lot_code"}


def test_login_validation_missing_field(client):
    err = assert_error(client.post("/api/auth/login", json={"email": "owner@everest.test"}),
                       422, "VALIDATION_FAILED")
    assert "password" in err["fields"]


def test_unknown_route_is_404_envelope(client):
    assert_error(client.get("/api/does-not-exist"), 404, "NOT_FOUND")


def test_unhandled_exception_is_500_without_leaks(client):
    res = client.get("/api/_test/boom")
    err = assert_error(res, 500, "INTERNAL")
    assert "SELECT" not in res.text and "Traceback" not in res.text and "password_hash" not in res.text
    assert res.headers.get("X-Request-ID")


# ---------- SQLSTATE -> code mapping (real errors raised by PostgreSQL) ----------
@pytest.fixture(scope="module")
def raw():
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        yield conn


def raise_in_db(conn, sqlstate: str, message: str = "boom", constraint: str | None = None,
                hint: str | None = None, detail: str | None = None) -> psycopg.Error:
    # RAISE ... USING takes expressions, so a temp function lets the values stay bind parameters.
    conn.execute("""
        CREATE OR REPLACE FUNCTION pg_temp.raise_it(p_state text, p_msg text, p_con text, p_hint text, p_detail text)
        RETURNS void LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION USING ERRCODE = p_state, MESSAGE = p_msg,
                  CONSTRAINT = coalesce(p_con, ''), HINT = coalesce(p_hint, ''), DETAIL = coalesce(p_detail, '');
        END $$""")
    with pytest.raises(psycopg.Error) as exc:
        conn.execute("SELECT pg_temp.raise_it(%s, %s, %s, %s, %s)", (sqlstate, message, constraint, hint, detail))
    return exc.value


@pytest.mark.parametrize("state,constraint,detail,status,code", [
    ("LL001", None, None, 409, "LOT_QUARANTINED"),
    ("LL002", None, None, 422, "INSUFFICIENT_STOCK"),
    ("LL003", None, None, 405, "LEDGER_IMMUTABLE"),
    ("23P01", "no_machine_double_booking", None, 409, "MACHINE_BUSY"),
    ("23505", "one_dispatch_per_roll", None, 409, "ALREADY_DISPATCHED"),
    ("23505", "stock_move_idempotency_key_key", None, 409, "DUPLICATE_REQUEST"),
    ("23505", "lot_code_key", "Key (code)=(Y-112) already exists.", 422, "VALIDATION_FAILED"),
    ("23503", "lot_product_id_kind_fkey", "Key (product_id)=(9) is not present.", 422, "VALIDATION_FAILED"),
    ("23514", "lot_qty_check", None, 422, "VALIDATION_FAILED"),
    ("23502", None, None, 422, "VALIDATION_FAILED"),
    ("22P02", None, None, 422, "VALIDATION_FAILED"),
    ("P0002", None, None, 404, "NOT_FOUND"),
    ("40P01", None, None, 409, "CONFLICT_RETRY"),
    ("XX000", None, None, 500, "INTERNAL"),
])
def test_map_db_error(raw, state, constraint, detail, status, code):
    err = map_db_error(raise_in_db(raw, state, "secret SQL text", constraint=constraint, detail=detail))
    assert (err.status, err.code) == (status, code)
    if code == "INTERNAL":
        assert "secret" not in err.message and err.sqlstate is None
    else:
        assert err.sqlstate == state


def test_map_db_error_business_messages_pass_through(raw):
    err = map_db_error(raise_in_db(raw, "LL001", "stock movement blocked: lot Y-112 is quarantined",
                                   hint="Quarantined stock can only go to quarantine, scrap, or back to the supplier."))
    mock = load_mock("error_lot_quarantined")["error"]
    assert err.body()["error"] == {**mock, "fields": None}


def test_map_db_error_fields_name_the_column(raw):
    err = map_db_error(raise_in_db(raw, "23505", constraint="lot_code_key", detail="Key (code)=(Y-112) already exists."))
    assert err.fields == {"code": "already exists"}
    assert "Y-112" not in err.message


def test_real_ledger_rewrite_maps_to_405(raw):
    with pytest.raises(psycopg.Error) as exc, raw.transaction():
        raw.execute("UPDATE stock_move SET qty = qty WHERE id = (SELECT min(id) FROM stock_move)")
    assert map_db_error(exc.value).code == "LEDGER_IMMUTABLE"


def test_idempotency_replay_detection(raw):
    assert is_idempotency_replay(raise_in_db(raw, "23505", constraint="stock_move_idempotency_key_key"))
    assert not is_idempotency_replay(raise_in_db(raw, "23505", constraint="one_dispatch_per_roll"))
