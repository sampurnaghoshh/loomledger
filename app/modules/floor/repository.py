"""Floor SQL. Reads come from 005 (v_machine_now, floor_output, machine_availability)."""
from __future__ import annotations

from datetime import date, datetime

import psycopg


def machines_now(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        """SELECT code, name, stage::text AS stage, state::text AS state, state_since, reason,
                  current_run, current_lot, current_order
             FROM v_machine_now ORDER BY code""").fetchall()


def output_day(conn: psycopg.Connection, day: date | None) -> date:
    return conn.execute("SELECT COALESCE(%s::date, (now() AT TIME ZONE 'Asia/Kolkata')::date) AS day",
                        (day,)).fetchone()["day"]


def output(conn: psycopg.Connection, day: date) -> list[dict]:
    return conn.execute(
        """SELECT machine_code, machine_name, stage::text AS stage, runs_completed, meters
             FROM floor_output(%s)""", (day,)).fetchall()


def availability_window(conn: psycopg.Connection, from_: datetime | None, to: datetime | None) -> dict:
    """Resolve the window in mill time; naive inputs are read as IST. Default: the 30 days before today."""
    return conn.execute(
        """WITH today AS (SELECT date_trunc('day', now() AT TIME ZONE 'Asia/Kolkata')
                                 AT TIME ZONE 'Asia/Kolkata' AS midnight)
           SELECT COALESCE(%(f)s::timestamptz, midnight - interval '30 days') AS from_,
                  COALESCE(%(t)s::timestamptz, midnight) AS "to"
             FROM today""",
        {"f": from_, "t": to}).fetchone()


def availability(conn: psycopg.Connection, from_: datetime, to: datetime) -> list[dict]:
    return conn.execute(
        """SELECT machine_code, running_h, breakdown_h, availability_pct
             FROM machine_availability(%s, %s)""", (from_, to)).fetchall()


def lock_machine(conn: psycopg.Connection, code: str) -> dict | None:
    """Row-lock the machine so two state changes for it are applied one after the other."""
    return conn.execute("SELECT id, code FROM machine WHERE code = %s AND active FOR UPDATE", (code,)).fetchone()


def close_open_state(conn: psycopg.Connection, machine_id: int) -> None:
    conn.execute("UPDATE machine_state_log SET ended_at = now() WHERE machine_id = %s AND ended_at IS NULL",
                 (machine_id,))


def open_state(conn: psycopg.Connection, machine_id: int, state: str, reason: str | None) -> datetime:
    return conn.execute(
        """INSERT INTO machine_state_log (machine_id, state, reason, started_at)
           VALUES (%s, %s, %s, now()) RETURNING started_at""", (machine_id, state, reason)).fetchone()["started_at"]
