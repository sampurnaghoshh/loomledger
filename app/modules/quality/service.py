"""Quality business flows."""
from __future__ import annotations

import uuid

import psycopg

from app import ledger
from app.db import write_tx
from app.errors import ApiError, is_idempotency_replay
from app.modules.quality import repository as repo
from app.modules.quality.schemas import InspectionRequest


def queue(conn: psycopg.Connection) -> list[dict]:
    return repo.queue(conn)


def rejections(conn: psycopg.Connection) -> list[dict]:
    return repo.rejections(conn)


def latest_rejections(conn: psycopg.Connection) -> dict:
    """The rejections of the latest day anything was rejected — by the mill's calendar, not the viewer's clock,
    so a Sunday presentation still shows Saturday's rejections as the latest."""
    day = repo.latest_rejection_day(conn)
    return {"day": day, "rejections": repo.rejections(conn, day) if day else []}


def inspect(conn: psycopg.Connection, req: InspectionRequest, user: dict) -> tuple[dict, bool]:
    """Record a QC verdict on a finished roll. A rejected roll is also physically moved from the
    finished-goods store to the reject bay, in the same transaction. Returns (result, created)."""
    if req.idempotency_key and req.result == "reject":
        original = repo.reject_replay(conn, req.idempotency_key)
        if original:
            return original, False
    try:
        with write_tx(conn):
            lot = repo.roll_lot(conn, req.lot_code)
            if lot is None:
                raise ApiError("NOT_FOUND", f"Roll {req.lot_code} not found.", 404,
                               fields={"lot_code": "not found"})
            inspector = repo.inspector(conn, req.inspector_code)
            if inspector is None:
                raise ApiError("NOT_FOUND", f"Inspector {req.inspector_code} not found.", 404,
                               fields={"inspector_code": "not found"})
            inspection_id = repo.insert_inspection(conn, lot["id"], inspector["id"], req.result,
                                                   req.defect_type, req.defect_meters, req.notes)
            if req.result == "reject":
                ledger.post_move(conn, lot_id=lot["id"], src=repo.FG_STORE, dst=repo.REJECT_BAY, qty=lot["qty"],
                                 kind="transfer", idempotency_key=req.idempotency_key or f"reject:{uuid.uuid4()}",
                                 user_id=user["id"])
    except psycopg.errors.UniqueViolation as exc:
        if is_idempotency_replay(exc) and req.idempotency_key and \
                (original := repo.reject_replay(conn, req.idempotency_key)):
            return original, False
        raise
    return {"inspection_id": inspection_id, "lot_code": lot["code"], "result": req.result}, True


def page_queue(conn: psycopg.Connection, query, filters: dict) -> dict:
    return repo.QUEUE_LIST.fetch(conn, query, filters)


def page_rejections(conn: psycopg.Connection, query, filters: dict) -> dict:
    return repo.REJECTION_LIST.fetch(conn, query, filters)
