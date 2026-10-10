"""Workforce SQL: the attendance register (001 attendance + 012 attendance_batch) and wages() (012)."""
from __future__ import annotations

from datetime import date

import psycopg

from app.listing import Filter, Listing


def last_working_day(conn: psycopg.Connection) -> date:
    """Today in mill time, or the Saturday before on a Sunday (the mill works Mon–Sat)."""
    return conn.execute("SELECT last_working_day((now() AT TIME ZONE 'Asia/Kolkata')::date) AS d").fetchone()["d"]


def shifts(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        """SELECT code, name, to_char(starts_at, 'HH24:MI') AS starts_at, to_char(ends_at, 'HH24:MI') AS ends_at
             FROM shift ORDER BY code""").fetchall()


def register(conn: psycopg.Connection, day: date) -> list[dict]:
    return conn.execute(
        """SELECT w.code AS worker_code, w.full_name, w.skill::text AS skill, a.status, s.code AS shift_code
             FROM worker w
             LEFT JOIN attendance a ON a.worker_id = w.id AND a.work_date = %s
             LEFT JOIN shift s      ON s.id = a.shift_id
            WHERE w.active
            ORDER BY w.code""", (day,)).fetchall()


def batch_replay(conn: psycopg.Connection, idempotency_key: str) -> dict | None:
    return conn.execute(
        """SELECT b.id AS batch_id, b.work_date AS day, s.code AS shift_code, b.marked, b.marked_at
             FROM attendance_batch b JOIN shift s ON s.id = b.shift_id
            WHERE b.idempotency_key = %s""", (idempotency_key,)).fetchone()


def shift_id(conn: psycopg.Connection, code: str) -> int | None:
    row = conn.execute("SELECT id FROM shift WHERE code = %s", (code,)).fetchone()
    return row["id"] if row else None


def worker_ids(conn: psycopg.Connection, codes: list[str]) -> dict[str, int]:
    """Every worker with one of these codes, active or not (the database refuses inactive ones: LL008)."""
    return {r["code"]: r["id"] for r in conn.execute("SELECT code, id FROM worker WHERE code = ANY(%s)", (codes,))}


def insert_batch(conn: psycopg.Connection, key: str, day: date, shift: int, user_id: int) -> dict:
    return conn.execute(
        """INSERT INTO attendance_batch (idempotency_key, work_date, shift_id, marked_by)
           VALUES (%s, %s, %s, %s) RETURNING id, marked_at""", (key, day, shift, user_id)).fetchone()


def upsert_attendance(conn: psycopg.Connection, worker_id: int, day: date, shift: int, status: str, batch_id: int) -> None:
    """One row per worker per day (the primary key): marking again corrects the day's row."""
    conn.execute(
        """INSERT INTO attendance (worker_id, work_date, shift_id, status, batch_id)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (worker_id, work_date)
           DO UPDATE SET shift_id = EXCLUDED.shift_id, status = EXCLUDED.status, batch_id = EXCLUDED.batch_id""",
        (worker_id, day, shift, status, batch_id))


def set_marked(conn: psycopg.Connection, batch_id: int, marked: int) -> None:
    conn.execute("UPDATE attendance_batch SET marked = %s WHERE id = %s", (marked, batch_id))


def month_to_date(conn: psycopg.Connection) -> tuple[date, date]:
    row = conn.execute(
        """SELECT date_trunc('month', (now() AT TIME ZONE 'Asia/Kolkata'))::date AS f,
                  (now() AT TIME ZONE 'Asia/Kolkata')::date AS t""").fetchone()
    return row["f"], row["t"]


def wages(conn: psycopg.Connection, from_: date, to: date) -> list[dict]:
    return conn.execute("SELECT * FROM wages(%s, %s)", (from_, to)).fetchall()


WORKER_LIST = Listing(
    source="SELECT code, full_name, skill::text AS skill, hourly_wage, active FROM worker",
    sort={"code": "code", "full_name": "full_name", "hourly_wage": "hourly_wage", "skill": "skill"},
    default_sort="code", tiebreak="code",
    search=("code", "full_name"),
    filters={"skill": Filter("skill"), "active": Filter("active")})
