"""Users SQL (017): the list, and set_user_access() — the one way to change a role or (de)activate someone."""
from __future__ import annotations

import psycopg

from app.listing import Filter, Listing

USER_LIST = Listing(
    source="SELECT id, email, full_name, role::text AS role, active, created_at FROM app_user",
    sort={"email": "email", "full_name": "full_name", "role": "role", "active": "active", "created_at": "created_at"},
    default_sort="email", tiebreak="id",
    search=("email", "full_name"),
    filters={"role": Filter("role"), "active": Filter("active")})


def set_access(conn: psycopg.Connection, actor_id: int, user_id: int, role: str | None, active: bool | None) -> dict:
    """LL011 (last active owner) and LL012 (deactivating yourself) are raised by the database; it also audits."""
    return conn.execute(
        """SELECT u.id, u.email, u.full_name, u.role::text AS role, u.active, u.created_at
             FROM set_user_access(%s, %s, %s::text::user_role, %s) u""", (actor_id, user_id, role, active)).fetchone()
