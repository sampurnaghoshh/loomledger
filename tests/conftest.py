"""Test fixtures: every test module/function gets a freshly migrated and seeded database.

Set TEST_DATABASE_URL to a database the tests may wipe (its public schema is dropped and recreated).
"""
from __future__ import annotations

import os

import psycopg
import pytest

from db.migrate import migrate, reset_schema
from seed.seed import seed

TEST_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/loomledger_test")


def _fresh() -> psycopg.Connection:
    conn = psycopg.connect(TEST_URL)
    reset_schema(conn)
    migrate(conn)
    seed(conn)
    return conn


@pytest.fixture(scope="module")
def db():
    """Seeded database shared by read-only tests in one module. Tests that write roll back."""
    conn = _fresh()
    yield conn
    conn.close()


@pytest.fixture
def fresh_db():
    """Seeded database owned by a single test (for tests that commit changes)."""
    conn = _fresh()
    yield conn
    conn.close()


def lot_id(conn: psycopg.Connection, code: str) -> int:
    return conn.execute("SELECT id FROM lot WHERE code = %s", (code,)).fetchone()[0]


def loc_id(conn: psycopg.Connection, code: str) -> int:
    return conn.execute("SELECT id FROM location WHERE code = %s", (code,)).fetchone()[0]


def rows(conn: psycopg.Connection, sql: str, params: tuple = ()) -> list[dict]:
    cur = conn.execute(sql, params)
    cols = [c.name for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]
