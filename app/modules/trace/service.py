"""Trace (Act 2): where did these rolls come from, and what do the rejected ones have in common?"""
from __future__ import annotations

import psycopg

from app.errors import ApiError
from app.modules.trace import repository as repo


def _resolve(conn: psycopg.Connection, codes: list[str], field: str) -> list[int]:
    found = repo.lot_ids(conn, codes)
    unknown = [c for c in codes if c not in found]
    if unknown:
        raise ApiError("NOT_FOUND", f"Unknown lot(s): {', '.join(unknown)}.", 404,
                       fields={field: f"unknown: {', '.join(unknown)}"})
    return [found[c] for c in codes]


def find_cause(conn: psycopg.Connection, lot_codes: list[str]) -> dict:
    """Compare defect rates through every factor the selected rolls share. Ranking and verdicts are find_cause()'s."""
    return {"selected": lot_codes, "factors": repo.find_cause(conn, _resolve(conn, lot_codes, "lot_codes"))}


def _graph(conn: psycopg.Connection, ids: list[int]) -> dict:
    return {"nodes": repo.nodes(conn, ids), "edges": repo.edges(conn, ids)}


def graph(conn: psycopg.Connection, lot_codes: list[str], direction: str) -> dict:
    ids = _resolve(conn, lot_codes, "lot_codes")
    family = repo.with_ancestors(conn, ids) if direction == "up" else repo.with_descendants(conn, ids)
    return {"lot_codes": lot_codes, **_graph(conn, family)}


def descendants(conn: psycopg.Connection, lot_code: str) -> dict:
    ids = _resolve(conn, [lot_code], "lot_code")
    return {"lot_code": lot_code, **_graph(conn, repo.with_descendants(conn, ids))}
