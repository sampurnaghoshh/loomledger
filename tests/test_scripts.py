"""Small script helpers: creating a separate database for private rehearsals."""
from __future__ import annotations

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from scripts.ensure_db import ensure_database
from tests.conftest import TEST_URL


def test_ensure_database_creates_once_then_reuses():
    url = make_conninfo(TEST_URL, dbname="loomledger_ensure_db_test")
    admin = make_conninfo(TEST_URL, dbname="postgres")
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS loomledger_ensure_db_test")
    try:
        assert ensure_database(url) is True        # created
        assert ensure_database(url) is False       # already there: left alone
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute("DROP DATABASE IF EXISTS loomledger_ensure_db_test")


def test_ensure_database_refuses_odd_names():
    with pytest.raises(SystemExit):
        ensure_database(make_conninfo(TEST_URL, dbname='x"; DROP DATABASE loomledger; --'))
