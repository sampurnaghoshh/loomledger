"""Posting to the ledger (stock_move). Shared by every module that moves stock.

The database guards every insert (002): LL001 quarantine, LL002 stock sufficiency, append-only.
This helper never checks those itself — it only turns location codes into ids.
"""
from __future__ import annotations

import psycopg


def post_move(conn: psycopg.Connection, *, lot_id: int, src: str, dst: str, qty: float, kind: str,
              idempotency_key: str, user_id: int, run_id: int | None = None,
              dispatch_id: int | None = None) -> None:
    cur = conn.execute(
        """INSERT INTO stock_move (lot_id, from_location_id, to_location_id, qty, kind,
                                   process_run_id, dispatch_id, idempotency_key, created_by)
           SELECT %s, f.id, t.id, %s, %s, %s, %s, %s, %s
             FROM location f, location t
            WHERE f.code = %s AND t.code = %s""",
        (lot_id, qty, kind, run_id, dispatch_id, idempotency_key, user_id, src, dst))
    if cur.rowcount != 1:      # a location master row is missing: a setup bug, never a user error
        raise RuntimeError(f"post_move: unknown location {src!r} or {dst!r}")
