"""Workforce: attendance register + wages. Exact values vs scenario.expected_register(); every error path."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import psycopg
import pytest
from psycopg.rows import dict_row

from seed import scenario as S
from tests.api.conftest import assert_same_shape, bearer, load_mock, login
from tests.conftest import TEST_URL

pytestmark = pytest.mark.usefixtures("reseed_after_module")
REG, WAGES = "/api/workforce/attendance", "/api/workforce/wages"


def q(sql: str, params: tuple = ()) -> list[dict]:
    with psycopg.connect(TEST_URL, row_factory=dict_row, autocommit=True) as conn:
        return conn.execute(sql, params).fetchall()


def x(sql: str, params: tuple = ()) -> None:
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        conn.execute(sql, params)


def today() -> date:
    return q("SELECT (now() AT TIME ZONE 'Asia/Kolkata')::date AS d")[0]["d"]


@pytest.fixture(scope="module")
def auth(client) -> dict[str, dict]:
    return {r: bearer(login(client, f"{r}@everest.test")) for r in ("owner", "floor", "accounts", "qc", "store")}


def sunday_run_days(code: str, f: date, t: date) -> set[date]:
    """Sundays the worker operated a run — the seed keeps those run-implied 'present' rows."""
    rows = q("""SELECT DISTINCT (r.started_at AT TIME ZONE 'Asia/Kolkata')::date AS d
                  FROM process_run r JOIN worker w ON w.id = r.operator_id
                 WHERE w.code = %s AND extract(isodow FROM r.started_at AT TIME ZONE 'Asia/Kolkata') = 7""", (code,))
    return {r["d"] for r in rows if f <= r["d"] <= t}


# ---------- reads (before any write) ----------
def test_register_for_the_demo_day_matches_contract(client, auth):
    res = client.get(REG, params={"day": S.ANCHOR_DATE.isoformat()}, headers=auth["floor"])
    assert res.status_code == 200, res.text
    mock = load_mock("workforce_attendance")
    assert_same_shape(res.json(), mock)
    assert res.json() == mock
    expected = S.expected_register()
    for w in res.json()["workers"]:
        assert (w["status"], w["shift_code"]) == expected[w["worker_code"]][S.ANCHOR_DATE] or w["status"] == "present", w


def test_register_defaults_to_today(client, auth):
    assert client.get(REG, headers=auth["owner"]).json()["day"] == today().isoformat()


def test_wages_match_contract_and_the_scenario(client, auth):
    month_from = date(S.ANCHOR_DATE.year, S.ANCHOR_DATE.month, 1)
    res = client.get(WAGES, params={"from": month_from.isoformat(), "to": S.ANCHOR_DATE.isoformat()}, headers=auth["accounts"])
    assert res.status_code == 200, res.text
    body, mock = res.json(), load_mock("workforce_wages")
    assert_same_shape(body, mock)
    assert body == mock

    register = S.expected_register()
    for w in body["workers"]:
        days = {d: st for d, (st, _) in register[w["worker_code"]].items() if month_from <= d <= S.ANCHOR_DATE}
        worked = [st for st in days.values() if st in ("present", "half_day")]
        sundays = sunday_run_days(w["worker_code"], month_from, S.ANCHOR_DATE)
        shifts = sum(1 if st == "present" else 0.5 for st in worked) + len(sundays)
        assert w["days_worked"] == len(worked) + len(sundays), w["worker_code"]
        assert w["shifts_worked"] == shifts, w["worker_code"]
        assert (w["half_days"], w["absent_days"], w["leave_days"]) == (
            list(days.values()).count("half_day"), list(days.values()).count("absent"), list(days.values()).count("leave"))
        assert w["gross_wage"] == round(w["hourly_wage"] * S.SHIFT_HOURS * shifts, 2), w["worker_code"]
    assert body["totals"]["gross_wage"] == pytest.approx(sum(w["gross_wage"] for w in body["workers"]))


def test_every_exception_shows_up_in_its_month(client, auth):
    for (code, offset), status in S.ATTENDANCE_EXCEPTIONS.items():
        d = S.ANCHOR_DATE + timedelta(days=offset)
        row = next(w for w in client.get(WAGES, params={"from": d.isoformat(), "to": d.isoformat()},
                                         headers=auth["owner"]).json()["workers"] if w["worker_code"] == code)
        key = {"absent": "absent_days", "half_day": "half_days", "leave": "leave_days"}[status]
        assert row[key] == 1, (code, d, status)


def test_wages_default_to_this_month(client, auth):
    body = client.get(WAGES, headers=auth["accounts"]).json()
    assert body["to"] == today().isoformat() and body["from"] == today().replace(day=1).isoformat()


@pytest.mark.parametrize("path,role", [(REG, "qc"), (REG, "accounts"), (WAGES, "floor"), (WAGES, "qc")])
def test_wrong_role_is_403(client, auth, path, role):
    assert client.get(path, headers=auth[role]).status_code == 403


@pytest.mark.parametrize("path", [REG, WAGES])
def test_needs_token(client, path):
    assert client.get(path).status_code == 401


def test_wages_bad_window_is_422(client, auth):
    res = client.get(WAGES, params={"from": "2026-10-10", "to": "2026-10-01"}, headers=auth["owner"])
    assert res.status_code == 422 and "from" in res.json()["error"]["fields"]


# ---------- marking the register ----------
def mark_body(day: date, marks: list[tuple[str, str]], shift: str = "A", key: str | None = None) -> dict:
    return {"day": day.isoformat(), "shift_code": shift, "marks": [{"worker_code": c, "status": s} for c, s in marks],
            "idempotency_key": key or str(uuid.uuid4())}


def test_mark_a_shift_in_one_request_and_replay(client, auth):
    codes = list(S.WORKER_SHIFT)
    body = mark_body(today(), [(c, "present") for c in codes])
    res = client.post(REG, json=body, headers=auth["floor"])
    assert res.status_code == 201, res.text
    assert (res.json()["marked"], res.json()["shift_code"]) == (len(codes), "A")
    again = client.post(REG, json=body, headers=auth["floor"])
    assert again.status_code == 200 and again.json() == res.json()        # replay: nothing written twice

    register = {w["worker_code"]: w for w in client.get(REG, headers=auth["floor"]).json()["workers"]}
    assert all(register[c]["status"] == "present" and register[c]["shift_code"] == "A" for c in codes)


def test_marking_again_corrects_the_day(client, auth):
    who = next(iter(S.WORKER_SHIFT))
    res = client.post(REG, json=mark_body(today(), [(who, "half_day")], shift="B"), headers=auth["owner"])
    assert res.status_code == 201
    rows = q("""SELECT a.status, s.code FROM attendance a JOIN worker w ON w.id = a.worker_id JOIN shift s ON s.id = a.shift_id
                 WHERE w.code = %s AND a.work_date = %s""", (who, today()))
    assert rows == [{"status": "half_day", "code": "B"}]                   # still one row for the day


def test_future_day_is_refused_by_the_database(client, auth):
    res = client.post(REG, json=mark_body(today() + timedelta(days=1), [("W-01", "present")]), headers=auth["floor"])
    assert res.status_code == 422
    assert (res.json()["error"]["code"], res.json()["error"]["sqlstate"]) == ("ATTENDANCE_FUTURE_DATE", "LL007")


def test_inactive_worker_is_refused_and_nothing_is_written(client, auth):
    x("UPDATE worker SET active = false WHERE code = 'Q-02'")
    try:
        batches = q("SELECT count(*) AS n FROM attendance_batch")[0]["n"]
        res = client.post(REG, json=mark_body(today(), [("Q-01", "absent"), ("Q-02", "present")]), headers=auth["floor"])
        assert res.status_code == 422
        assert (res.json()["error"]["code"], res.json()["error"]["sqlstate"]) == ("WORKER_INACTIVE", "LL008")
        assert q("SELECT count(*) AS n FROM attendance_batch")[0]["n"] == batches        # one transaction
    finally:
        x("UPDATE worker SET active = true WHERE code = 'Q-02'")


@pytest.mark.parametrize("marks,shift,field", [([("W-99", "present")], "A", "marks"), ([("W-01", "present")], "Z", "shift_code")])
def test_unknown_worker_or_shift_is_404(client, auth, marks, shift, field):
    res = client.post(REG, json=mark_body(today(), marks, shift=shift), headers=auth["floor"])
    assert res.status_code == 404 and field in res.json()["error"]["fields"]


@pytest.mark.parametrize("body", [
    lambda: mark_body(today(), []),
    lambda: mark_body(today(), [("W-01", "present"), ("W-01", "absent")]),
    lambda: mark_body(today(), [("W-01", "sleeping")]),
    lambda: {**mark_body(today(), [("W-01", "present")]), "idempotency_key": "x"},
])
def test_bad_body_is_422(client, auth, body):
    res = client.post(REG, json=body(), headers=auth["floor"])
    assert res.status_code == 422 and res.json()["error"]["code"] == "VALIDATION_FAILED"


@pytest.mark.parametrize("role", ["store", "qc", "accounts"])
def test_mark_wrong_role_is_403(client, auth, role):
    assert client.post(REG, json=mark_body(today(), [("W-01", "present")]), headers=auth[role]).status_code == 403


def test_mark_needs_token(client):
    assert client.post(REG, json=mark_body(today(), [("W-01", "present")])).status_code == 401
