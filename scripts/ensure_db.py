"""Create the database named in a PostgreSQL URL if it does not exist yet (e.g. loomledger_rehearsal).

    python -m scripts.ensure_db postgresql://postgres:postgres@localhost:5432/loomledger_rehearsal
"""
from __future__ import annotations

import re
import sys

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo


def ensure_database(url: str) -> bool:
    """Returns True if it created the database, False if it already existed."""
    name = conninfo_to_dict(url).get("dbname")
    if not name or not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise SystemExit(f"refusing to create database {name!r}: use letters, digits and _ only")
    admin = make_conninfo(url, dbname="postgres")              # same server and credentials, maintenance DB
    with psycopg.connect(admin, autocommit=True) as conn:
        if conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
            return False
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        return True


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    created = ensure_database(sys.argv[1])
    print(f"database {conninfo_to_dict(sys.argv[1])['dbname']}: {'created' if created else 'exists'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
