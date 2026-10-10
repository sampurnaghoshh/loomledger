"""Phase guard + validation log (migration 018), through the API.

A phase skip is refused by the database (409 PHASE_SKIPPED, fields.missing_phase) and, like every write a business
rule refuses, recorded in validation_log exactly once — on a separate connection, so the record survives the rollback.
Successful writes and malformed requests (VALIDATION_FAILED) are not logged; a failure to log never changes the
response; secrets in the input are redacted. GET /api/validation-log: owner / qc, paged + filters."""
from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg.rows import dict_row

from tests.api.conftest import bearer, login
from tests.conftest import TEST_URL

pytestmark = pytest.mark.usefixtures("reseed_after_module")
INSPECT, LOG = "/api/quality/inspections", "/api/validation-log"


def q(sql: str, params: tuple = ()) -> list[dict]:
    with psycopg.connect(TEST_URL, row_factory=dict_row, autocommit=True) as conn:
        return conn.execute(sql, params).fetchall()


def log_rows() -> list[dict]:
    return q("SELECT * FROM validation_log ORDER BY id")


@pytest.fixture(scope="module")
def auth(client) -> dict[str, dict]:
    return {r: bearer(login(client, f"{r}@everest.test")) for r in ("owner", "qc", "store", "floor")}


def test_qc_on_a_greige_roll_is_a_phase_skip_and_is_logged_once(client, auth):
    before, inspections = len(log_rows()), q("SELECT count(*) AS n FROM qc_inspection")[0]["n"]
    res = client.post(INSPECT, json={"lot_code": "R-1213-G", "result": "pass"}, headers=auth["qc"])
    assert res.status_code == 409, res.text
    err = res.json()["error"]
    assert (err["code"], err["sqlstate"], err["fields"]["missing_phase"]) == ("PHASE_SKIPPED", "LL013", "dyeing")
    assert "R-1213-G" in err["message"] and err["hint"]
    assert q("SELECT count(*) AS n FROM qc_inspection")[0]["n"] == inspections          # nothing was written
    rows = log_rows()[before:]
    assert len(rows) == 1
    row = rows[0]
    assert (row["user_email"], row["role"], row["method"], row["path"], row["status"], row["error_code"], row["sqlstate"]) == \
        ("qc@everest.test", "qc", "POST", INSPECT, 409, "PHASE_SKIPPED", "LL013")
    assert row["input_summary"] == {"lot_code": "R-1213-G", "result": "pass"}


def test_dispatch_before_qc_pass_is_refused_and_logged(client, auth):
    before = len(log_rows())
    res = client.post("/api/dispatches", headers=auth["store"], json={
        "order_code": "SO-0419", "lot_codes": ["R-1209"], "vehicle_no": "KA-01-T-1", "idempotency_key": str(uuid.uuid4())})
    assert res.status_code == 409 and res.json()["error"]["code"] == "NOT_QC_PASSED"
    assert [r["error_code"] for r in log_rows()[before:]] == ["NOT_QC_PASSED"]


def test_successful_and_malformed_writes_are_not_logged(client, auth):
    before = len(log_rows())
    ok = client.post("/api/floor/machines/LOOM-3/state", json={"state": "changeover", "reason": "test"}, headers=auth["floor"])
    assert ok.status_code == 200
    bad = client.post(INSPECT, json={"lot_code": "not a roll", "result": "pass"}, headers=auth["qc"])
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "VALIDATION_FAILED"
    wrong_password = client.post("/api/auth/login", json={"email": "qc@everest.test", "password": "nope"})
    assert wrong_password.status_code == 401
    assert len(log_rows()) == before


def test_the_log_never_breaks_the_request(client, auth, monkeypatch):
    from app.modules.validation import repository, service

    def boom(*args, **kwargs):
        raise psycopg.OperationalError("log database unavailable")

    monkeypatch.setattr(repository, "insert", boom)
    before = len(log_rows())
    res = client.post(INSPECT, json={"lot_code": "R-1214-G", "result": "pass"}, headers=auth["qc"])
    assert res.status_code == 409 and res.json()["error"]["code"] == "PHASE_SKIPPED"         # the real refusal
    monkeypatch.setattr(service, "is_refusal", lambda *a, **k: 1 / 0)                       # even a bug in the hook
    res = client.post(INSPECT, json={"lot_code": "R-1214-G", "result": "pass"}, headers=auth["qc"])
    assert res.status_code == 409 and res.json()["error"]["code"] == "PHASE_SKIPPED"
    assert len(log_rows()) == before


def test_input_summary_is_short_and_redacted():
    from app.modules.validation.service import summarize

    s = summarize({"email": "a@b.c", "password": "hunter2", "api_token": "x", "notes": "n" * 200,
                   "lot_codes": [f"R-{i}" for i in range(20)], **{f"k{i}": i for i in range(20)}})
    assert s["password"] == s["api_token"] == "[redacted]"
    assert len(s["notes"]) == 61 and s["notes"].endswith("…")
    assert len(s) <= 13 and "…" in s


def test_validation_log_list(client, auth):
    body = client.get(LOG, params={"code": "PHASE_SKIPPED"}, headers=auth["owner"]).json()
    assert body["total"] >= 1 and {r["error_code"] for r in body["items"]} == {"PHASE_SKIPPED"}
    times = [r["at"] for r in client.get(LOG, headers=auth["qc"]).json()["items"]]
    assert times == sorted(times, reverse=True)                                           # newest first
    mine = client.get(LOG, params={"user": "store@everest.test"}, headers=auth["owner"]).json()
    assert {r["user_email"] for r in mine["items"]} == {"store@everest.test"}
    assert client.get(LOG, params={"since": "2100-01-01"}, headers=auth["owner"]).json()["total"] == 0
    assert client.get(LOG, params={"q": "R-1213-G"}, headers=auth["owner"]).json()["total"] >= 1
    assert client.get(LOG, params={"sort": "nope"}, headers=auth["owner"]).status_code == 422
    assert client.get(LOG, params={"code": "drop table"}, headers=auth["owner"]).status_code == 422
    assert client.get(LOG, headers=auth["store"]).status_code == 403
    assert client.get(LOG).status_code == 401
