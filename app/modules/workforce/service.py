"""Workforce: the daily attendance register and the wage run."""
from __future__ import annotations

from datetime import date

import psycopg

from app.db import write_tx
from app.errors import ApiError, is_idempotency_replay
from app.modules.workforce import repository as repo
from app.modules.workforce.schemas import MarkRequest


def register(conn: psycopg.Connection, day: date | None) -> dict:
    day = day or repo.last_working_day(conn)
    return {"day": day, "shifts": repo.shifts(conn), "workers": repo.register(conn, day)}


def mark(conn: psycopg.Connection, req: MarkRequest, user: dict) -> tuple[dict, bool]:
    """Save one shift's register in one transaction. The database refuses a future day (LL007) and an inactive
    worker (LL008); a resend with the same idempotency_key returns the original result. Returns (result, created)."""
    original = repo.batch_replay(conn, req.idempotency_key)
    if original:
        return original, False
    try:
        with write_tx(conn):
            shift = repo.shift_id(conn, req.shift_code)
            if shift is None:
                raise ApiError("NOT_FOUND", f"Shift {req.shift_code} not found.", 404, fields={"shift_code": "unknown shift"})
            ids = repo.worker_ids(conn, [m.worker_code for m in req.marks])
            unknown = [m.worker_code for m in req.marks if m.worker_code not in ids]
            if unknown:
                raise ApiError("NOT_FOUND", f"Unknown worker(s): {', '.join(unknown)}.", 404,
                               fields={"marks": f"unknown: {', '.join(unknown)}"})
            batch = repo.insert_batch(conn, req.idempotency_key, req.day, shift, user["id"])
            for m in req.marks:
                repo.upsert_attendance(conn, ids[m.worker_code], req.day, shift, m.status, batch["id"])
            repo.set_marked(conn, batch["id"], len(req.marks))
    except psycopg.errors.UniqueViolation as exc:
        if is_idempotency_replay(exc) and (original := repo.batch_replay(conn, req.idempotency_key)):
            return original, False
        raise
    return {"batch_id": batch["id"], "day": req.day, "shift_code": req.shift_code, "marked": len(req.marks),
            "marked_at": batch["marked_at"]}, True


def wages(conn: psycopg.Connection, from_: date | None, to: date | None) -> dict:
    """Gross wages per worker for [from, to] (default: this month to date): shifts x hourly wage x shift length."""
    default_from, default_to = repo.month_to_date(conn)
    from_, to = from_ or default_from, to or default_to
    if from_ > to:
        raise ApiError("VALIDATION_FAILED", "'from' must not be after 'to'.", 422, fields={"from": "after to"})
    rows = repo.wages(conn, from_, to)
    totals = {"workers": len(rows),
              "days_worked": sum(r["days_worked"] for r in rows),
              "shifts_worked": sum(r["shifts_worked"] for r in rows),
              "gross_wage": sum(r["gross_wage"] for r in rows)}
    return {"from_": from_, "to": to, "totals": totals, "workers": rows}
