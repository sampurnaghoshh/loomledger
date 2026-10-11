"""Roll passport: everything one roll's QR code should answer — what it is, where it is, where it came from,
what QC said, what it cost, who it is for, whether it shipped, and whether it is under recall."""
from __future__ import annotations

import psycopg

from app.errors import ApiError
from app.modules.rolls import repository as repo

RUN_FIELDS = ("stage", "machine", "shift", "operator", "started_at", "ended_at")


def _step(row: dict) -> dict:
    receipt = ({"code": row["receipt_code"], "supplier": row["supplier"], "received_at": row["received_at"]}
               if row["receipt_code"] else None)
    run = {"code": row["run_code"], **{k: row[k] for k in RUN_FIELDS}} if row["run_code"] else None
    return {"lot_code": row["lot_code"], "kind": row["kind"], "product": row["product"], "qty": row["qty"],
            "uom": row["uom"], "depth": row["depth"], "receipt": receipt, "run": run}


def passport(conn: psycopg.Connection, code: str) -> dict:
    roll = repo.roll(conn, code)
    if roll is None:
        raise ApiError("NOT_FOUND", f"Unknown roll: {code}.", 404, fields={"code": f"unknown: {code}"})
    lot_id = roll.pop("id")
    return {**roll,
            "lineage": [_step(r) for r in repo.lineage(conn, lot_id)],
            "qc": repo.latest_qc(conn, lot_id),
            "cost": repo.cost(conn, lot_id),
            "order": repo.order(conn, lot_id),
            "dispatch": repo.dispatch(conn, lot_id),
            "recall": repo.recall(conn, lot_id)}


def labels(conn: psycopg.Connection, root_code: str | None) -> dict:
    """QR labels to print: every roll downstream of the root (default: the yarn lot behind the latest QC rejection)
    and one clean roll for contrast."""
    if root_code is None:
        root = repo.last_rejection_yarn_lot(conn)
    else:
        root = repo.lot_by_code(conn, root_code)
        if root is None:
            raise ApiError("NOT_FOUND", f"Unknown lot: {root_code}.", 404, fields={"root": f"unknown: {root_code}"})
    root_id = root["id"] if root else None
    rolls = repo.scope_labels(conn, root_id) if root_id else []
    clean = repo.clean_label(conn, root_id)
    return {"root": root["code"] if root else None, "rolls": rolls + ([clean] if clean else [])}


def page_rolls(conn: psycopg.Connection, query, filters: dict) -> dict:
    """Every physical roll (greige on the loom / in store, finished), where it is, its order and latest QC."""
    return repo.ROLL_LIST.fetch(conn, query, filters)
