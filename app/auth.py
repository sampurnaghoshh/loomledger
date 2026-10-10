"""Login, signed bearer tokens, and role checks.

Passwords are verified by PostgreSQL (pgcrypto crypt()); Python never sees a hash.
Tokens are itsdangerous-signed {"uid": id} with a TTL; the user row is re-read on every request,
so a deleted or DEACTIVATED user, or a changed role, takes effect immediately (017).
Permissions live in the database (017 role_permission); routes ask require_permission("area.action").
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Header
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field

from app.config import get_settings
from app.db import get_conn
from app.errors import ApiError

router = APIRouter(prefix="/api/auth", tags=["auth"])

TOKEN_SALT = "loomledger-auth"
ROLES = ("owner", "store", "floor_supervisor", "qc", "accounts")


# ---------- schemas (field names = contract keys, docs/api-mocks/auth_login.json) ----------
class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str


class LoginResponse(BaseModel):
    token: str
    user: UserOut


# ---------- tokens ----------
def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().SECRET_KEY, salt=TOKEN_SALT)


def issue_token(user_id: int) -> str:
    return _serializer().dumps({"uid": user_id})


def read_token(token: str) -> int:
    max_age = get_settings().TOKEN_TTL_HOURS * 3600
    try:
        data = _serializer().loads(token, max_age=max_age)
    except SignatureExpired:
        raise unauthenticated("Your session has expired. Please sign in again.")
    except BadSignature:
        raise unauthenticated()
    uid = data.get("uid") if isinstance(data, dict) else None
    if not isinstance(uid, int):
        raise unauthenticated()
    return uid


def unauthenticated(message: str = "Please sign in.") -> ApiError:
    return ApiError("UNAUTHENTICATED", message, 401)


# ---------- repository ----------
def find_user_by_credentials(conn: psycopg.Connection, email: str, password: str) -> dict | None:
    return conn.execute(
        "SELECT id, email, full_name, role::text AS role FROM app_user"
        " WHERE lower(email) = lower(%s) AND password_hash = crypt(%s, password_hash) AND active",
        (email.strip(), password),
    ).fetchone()


def find_user(conn: psycopg.Connection, user_id: int) -> dict | None:
    return conn.execute(
        "SELECT id, email, full_name, role::text AS role FROM app_user WHERE id = %s AND active", (user_id,)).fetchone()


def has_permission(conn: psycopg.Connection, role: str, permission: str) -> bool:
    return conn.execute("SELECT 1 FROM role_permission WHERE role::text = %s AND permission = %s",
                        (role, permission)).fetchone() is not None


def permission_matrix(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        """SELECT p.code, p.area, p.description,
                  COALESCE(array_agg(rp.role::text ORDER BY rp.role) FILTER (WHERE rp.role IS NOT NULL), '{}') AS roles
             FROM permission p LEFT JOIN role_permission rp ON rp.permission = p.code
            GROUP BY p.code, p.area, p.description
            ORDER BY p.area, p.code""").fetchall()


# ---------- dependencies ----------
Conn = Annotated[psycopg.Connection, Depends(get_conn)]


def require_user(conn: Conn, authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise unauthenticated()
    user = find_user(conn, read_token(token.strip()))
    if user is None:
        raise unauthenticated()
    return user


CurrentUser = Annotated[dict[str, Any], Depends(require_user)]


def require_role(*roles: str) -> Callable[..., dict[str, Any]]:
    """Dependency factory: allow the listed roles; the owner is always allowed."""
    unknown = set(roles) - set(ROLES)
    if unknown:
        raise ValueError(f"unknown roles: {sorted(unknown)}")

    def check(user: CurrentUser) -> dict[str, Any]:
        if user["role"] != "owner" and user["role"] not in roles:
            raise ApiError("FORBIDDEN", "Your role is not allowed to do this.", 403)
        return user

    return check


def require_permission(permission: str) -> Callable[..., dict[str, Any]]:
    """Dependency factory: the signed-in user's role must hold `permission` in role_permission (017)."""

    def check(conn: Conn, user: CurrentUser) -> dict[str, Any]:
        if not has_permission(conn, user["role"], permission):
            raise ApiError("FORBIDDEN", "Your role is not allowed to do this.", 403)
        return user

    return check


class PermissionOut(BaseModel):
    code: str
    area: str
    description: str
    roles: list[str]


class MyPermissions(BaseModel):
    role: str
    permissions: list[str]


class PermissionsResponse(BaseModel):
    roles: list[str]
    permissions: list[PermissionOut]
    me: MyPermissions


# ---------- routes ----------
@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, conn: Conn) -> LoginResponse:
    user = find_user_by_credentials(conn, body.email, body.password)
    if user is None:
        raise ApiError("INVALID_CREDENTIALS", "Email or password is incorrect.", 401)
    return LoginResponse(token=issue_token(user["id"]), user=UserOut(**user))


@router.get("/permissions", response_model=PermissionsResponse)
def permissions(conn: Conn, user: CurrentUser) -> dict:
    """The role × permission matrix (017) and what the signed-in user may do. The UI hides what you can't use."""
    matrix = permission_matrix(conn)
    return {"roles": list(ROLES), "permissions": matrix,
            "me": {"role": user["role"], "permissions": [p["code"] for p in matrix if user["role"] in p["roles"]]}}
