"""Connection pool + per-request connection.

Pool connections run in autocommit, so reads never leave a transaction open. A service that writes
wraps its whole flow in `with write_tx(conn):` — exactly one transaction per request; the database's
triggers and constraints then decide whether it commits.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from fastapi import Request
from psycopg import pq
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

MILL_TIMEZONE = "Asia/Kolkata"


def _configure(conn: psycopg.Connection) -> None:
    # The database default is already IST (migration 001); setting it here keeps that true on any server.
    conn.execute("SELECT set_config('TimeZone', %s, false)", (MILL_TIMEZONE,))


def create_pool(conninfo: str, *, min_size: int = 1, max_size: int = 10) -> ConnectionPool:
    """Create a closed pool; the FastAPI lifespan opens and closes it."""
    return ConnectionPool(
        conninfo,
        min_size=min_size,
        max_size=max_size,
        kwargs={"row_factory": dict_row, "autocommit": True},
        configure=_configure,
        open=False,
        name="loomledger",
    )


def get_conn(request: Request) -> Iterator[psycopg.Connection]:
    """FastAPI dependency: one pooled connection for the duration of the request."""
    pool: ConnectionPool = request.app.state.pool
    with pool.connection() as conn:
        yield conn


@contextmanager
def write_tx(conn: psycopg.Connection) -> Iterator[psycopg.Connection]:
    """The single transaction of a write request. Commits on success, rolls back on any exception.

    Refuses to nest, so a request can't accidentally split its writes across transactions.
    """
    if conn.info.transaction_status != pq.TransactionStatus.IDLE:
        raise RuntimeError("write_tx: a transaction is already open on this connection")
    with conn.transaction():
        yield conn
