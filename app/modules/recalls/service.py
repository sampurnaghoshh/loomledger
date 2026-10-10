"""Recall (Acts 3–4): what a bad lot touched, what it costs, and containing it."""
from __future__ import annotations

import psycopg

from app.db import write_tx
from app.errors import ApiError
from app.modules.recalls import repository as repo

FORMULA = "additional_delay_days = ceil(remake_m / throughput_m_per_day)"


def _calculation(impact: dict) -> dict:
    """Spell out the DB's delay arithmetic for the screen. The numbers are recall_impact()'s; nothing is decided here."""
    remake, throughput, days = impact["remake_m"], impact["throughput_m_per_day"], impact["additional_delay_days"]
    if throughput:
        raw = float(remake) / float(throughput)
        display = f"{float(remake):g} ÷ {float(throughput):g} = {raw:g} → ceil = {days} working days"
    else:
        raw, display = 0.0, f"nothing to remake → {days} working days"
    return {"formula": FORMULA, "remake_m": remake, "throughput_m_per_day": throughput,
            "raw_days": round(raw, 2), "additional_delay_days": days, "display": display}


def _lot(conn: psycopg.Connection, lot_code: str) -> int:
    lot_id = repo.lot_id(conn, lot_code)
    if lot_id is None:
        raise ApiError("NOT_FOUND", f"Lot {lot_code} not found.", 404, fields={"lot_code": "not found"})
    return lot_id


def _payload(conn: psycopg.Connection, lot_code: str, lot_id: int) -> dict:
    impact = repo.impact(conn, lot_id)
    body = {"lot_code": lot_code, "impact": impact, "orders": repo.order_impact(conn, lot_id),
            "rolls": repo.rolls(conn, lot_id), "calculation": _calculation(impact)}
    recall = repo.recall_for(conn, lot_id)
    if recall is None:
        return {"applied": False, "recall_code": None, **body}
    return {"applied": True, "recall_code": recall["code"], "applied_at": recall["initiated_at"], **body}


def preview(conn: psycopg.Connection, lot_code: str) -> dict:
    """Everything downstream of the lot, where it is now, which orders slip and by how much, and the money.
    Once a recall exists for the lot, the same view carries the recall code and when it was applied."""
    return _payload(conn, lot_code, _lot(conn, lot_code))


def apply(conn: psycopg.Connection, lot_code: str, reason: str, user: dict) -> tuple[dict, bool]:
    """Quarantine the lot and everything it touched, revise the affected orders and tell their buyers —
    all inside apply_recall(). Applying again changes nothing and returns the same recall. Returns (body, created)."""
    lot_id = _lot(conn, lot_code)
    existed = repo.recall_for(conn, lot_id) is not None
    with write_tx(conn):
        repo.apply(conn, lot_id, reason, user["id"])
    return _payload(conn, lot_code, lot_id), not existed
