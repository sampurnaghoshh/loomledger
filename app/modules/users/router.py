"""Users & roles: owner only (permission users.manage, 017)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.auth import Conn, require_permission
from app.listing import ListParams, Page
from app.modules.users import service
from app.modules.users.schemas import AccessChange, Role, UserRow

router = APIRouter(prefix="/api/users", tags=["users"])
Manager = Annotated[dict, Depends(require_permission("users.manage"))]


@router.get("", response_model=Page[UserRow])
def users(conn: Conn, user: Manager, query: ListParams, role: Role | None = None, active: bool | None = None):
    """?q= (email, name) &sort=(-)email|full_name|role|active|created_at &role= &active="""
    return service.page_users(conn, query, {"role": role, "active": active})


@router.patch("/{user_id}", response_model=UserRow)
def change(body: AccessChange, conn: Conn, user: Manager, user_id: Annotated[int, Path(ge=1)]):
    """409 LAST_OWNER (LL011), 409 SELF_DEACTIVATION (LL012), 404 unknown user; audited with the acting owner."""
    return service.change_access(conn, user, user_id, body.role, body.active)
