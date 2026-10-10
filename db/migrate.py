"""Apply SQL migrations in db/migrations in filename order, each exactly once, each in its own transaction.

Usage:
    python -m db.migrate                 # uses DATABASE_URL
    python -m db.migrate --reset         # drop & recreate the public schema first (dev only)
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
DEFAULT_URL = "postgresql://postgres:postgres@localhost:5432/loomledger"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


def reset_schema(conn: psycopg.Connection) -> None:
    with conn.transaction():
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")


def migrate(conn: psycopg.Connection) -> list[str]:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
               filename   text PRIMARY KEY,
               applied_at timestamptz NOT NULL DEFAULT now())"""
    )
    conn.commit()
    applied = {r[0] for r in conn.execute("SELECT filename FROM schema_migrations")}
    conn.commit()   # end the implicit read transaction so each migration below is a real, committed transaction
    newly_applied: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in applied:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,))
        newly_applied.append(path.name)
    return newly_applied


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="drop and recreate the public schema first")
    args = parser.parse_args()
    with psycopg.connect(database_url(), autocommit=False) as conn:
        if args.reset:
            reset_schema(conn)
        done = migrate(conn)
    print("applied:", ", ".join(done) if done else "nothing (up to date)")


if __name__ == "__main__":
    main()
