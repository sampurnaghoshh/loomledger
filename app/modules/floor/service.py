"""Floor business flows."""
from __future__ import annotations

from datetime import date, datetime

import psycopg

from app.db import write_tx
from app.errors import ApiError, not_found
from app.modules.floor import repository as repo


def machines_now(conn: psycopg.Connection) -> list[dict]:
    return repo.machines_now(conn)


def output(conn: psycopg.Connection, day: date | None) -> dict:
    day = repo.output_day(conn, day)
    return {"day": day, "machines": repo.output(conn, day)}


def availability(conn: psycopg.Connection, from_: datetime | None, to: datetime | None) -> dict:
    window = repo.availability_window(conn, from_, to)
    if window["from_"] >= window["to"]:
        raise ApiError("VALIDATION_FAILED", "'from' must be before 'to'.", 422, fields={"from": "must be before to"})
    return {**window, "machines": repo.availability(conn, window["from_"], window["to"])}


def change_state(conn: psycopg.Connection, machine_code: str, state: str, reason: str | None) -> dict:
    """Close the machine's open state and open the new one — one transaction, so the floor board
    (via the machine_state_log NOTIFY trigger) only ever sees a complete change."""
    with write_tx(conn):
        machine = repo.lock_machine(conn, machine_code)
        if machine is None:
            raise not_found(f"Machine {machine_code} not found.")
        repo.close_open_state(conn, machine["id"])
        started_at = repo.open_state(conn, machine["id"], state, reason)
    return {"machine_code": machine["code"], "state": state, "started_at": started_at}
