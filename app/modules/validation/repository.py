"""Validation log SQL (018): one row per write a business rule refused; the list for owner / qc."""
from __future__ import annotations

import psycopg
from psycopg.types.json import Jsonb

from app.listing import Filter, Listing

LOG_LIST = Listing(
    source="""SELECT id, at, user_email, role, method, path, status, error_code, sqlstate, message, input_summary
                FROM validation_log""",
    sort={"at": "at", "error_code": "error_code", "user_email": "user_email", "status": "status", "path": "path"},
    default_sort="-at", tiebreak="id",
    search=("message", "path", "user_email", "error_code"),
    filters={"code": Filter("error_code"), "sqlstate": Filter("sqlstate"), "user": Filter("user_email"),
             "since": Filter("at", "gte"), "before": Filter("at", "lt")})


def insert(conn: psycopg.Connection, row: dict) -> None:
    conn.execute(
        """INSERT INTO validation_log (user_id, user_email, role, method, path, status, error_code, sqlstate, message,
                                       input_summary)
           VALUES (%(user_id)s, %(user_email)s, %(role)s, %(method)s, %(path)s, %(status)s, %(error_code)s,
                   %(sqlstate)s, %(message)s, %(input_summary)s)""",
        row | {"input_summary": Jsonb(row["input_summary"]) if row["input_summary"] is not None else None})
