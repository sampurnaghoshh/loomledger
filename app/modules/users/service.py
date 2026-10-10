"""Users & roles (owner): who can sign in, with which role. The rules live in the database (017)."""
from __future__ import annotations

import psycopg

from app.db import write_tx
from app.modules.users import repository as repo


def page_users(conn: psycopg.Connection, query, filters: dict) -> dict:
    return repo.USER_LIST.fetch(conn, query, filters)


def change_access(conn: psycopg.Connection, actor: dict, user_id: int, role: str | None, active: bool | None) -> dict:
    """Change a user's role and/or active flag in one transaction; set_user_access() checks and audits it."""
    with write_tx(conn):
        return repo.set_access(conn, actor["id"], user_id, role, active)
