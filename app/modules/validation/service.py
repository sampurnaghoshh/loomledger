"""Validation log: every write that a business rule refused (LL0xx, or another 409/422 from a rule), recorded on a
SEPARATE autocommit connection from the pool — the refused request's own transaction has already rolled back, and the
record must survive it. Recording never breaks the request: any failure here is only logged to the server log."""
from __future__ import annotations

import json
import logging
from typing import Any

import psycopg
from fastapi import Request

from app.modules.validation import repository as repo

log = logging.getLogger("loomledger.validation")
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
INPUT_FORMAT_CODES = {"VALIDATION_FAILED"}           # a malformed request, not a business rule
SECRET_HINTS = ("password", "token", "secret", "authorization", "key")
MAX_KEYS, MAX_STR, MAX_ITEMS = 12, 60, 5


def is_refusal(request: Request, status: int, code: str, sqlstate: str | None) -> bool:
    if request.method not in WRITE_METHODS or status not in (409, 422):
        return False
    return bool(sqlstate and sqlstate.startswith("LL")) or code not in INPUT_FORMAT_CODES


def summarize(value: Any, depth: int = 0) -> Any:
    """A short, safe picture of the input: secrets redacted, strings and lists truncated, nesting limited."""
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:MAX_KEYS]:
            out[str(k)[:40]] = "[redacted]" if any(h in str(k).lower() for h in SECRET_HINTS) else \
                (summarize(v, depth + 1) if depth < 2 else "…")
        if len(value) > MAX_KEYS:
            out["…"] = f"{len(value) - MAX_KEYS} more"
        return out
    if isinstance(value, list):
        items = [summarize(v, depth + 1) for v in value[:MAX_ITEMS]]
        return items + [f"… {len(value) - MAX_ITEMS} more"] if len(value) > MAX_ITEMS else items
    if isinstance(value, str):
        return value if len(value) <= MAX_STR else value[:MAX_STR] + "…"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:MAX_STR]


def record(request: Request, body: bytes, status: int, code: str, message: str, sqlstate: str | None) -> None:
    """Called by the error handlers (app/errors.py) in a worker thread. Never raises."""
    try:
        try:
            summary = summarize(json.loads(body)) if body else None
        except (ValueError, UnicodeDecodeError):
            summary = {"body": f"{len(body)} bytes, not JSON"}
        user = getattr(request.state, "user", None) or {}
        with request.app.state.pool.connection() as conn:          # pool connections are autocommit
            repo.insert(conn, {
                "user_id": user.get("id"), "user_email": user.get("email"), "role": user.get("role"),
                "method": request.method, "path": request.url.path[:200], "status": status,
                "error_code": code, "sqlstate": sqlstate, "message": message[:500], "input_summary": summary})
    except (psycopg.Error, OSError, RuntimeError, AttributeError, TypeError, ValueError) as exc:
        log.warning("could not record a refused write (%s): %s", type(exc).__name__, exc)


def page(conn: psycopg.Connection, query, filters: dict) -> dict:
    return repo.LOG_LIST.fetch(conn, query, filters)
