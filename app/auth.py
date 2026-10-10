"""Login, signed bearer tokens, and role checks.

Passwords are verified by PostgreSQL (pgcrypto crypt()); Python never sees a hash.
Tokens are itsdangerous-signed {"uid": id} with a TTL; the user row is re-read on every request,
so a deleted user or changed role takes effect immediately.
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
        " WHERE lower(email) = lower(%s) AND password_hash = crypt(%s, password_hash)",
        (email.strip(), password),
    ).fetchone()


def find_user(conn: psycopg.Connection, user_id: int) -> dict | None:
    return conn.execute(
        "SELECT id, email, full_name, role::text AS role FROM app_user WHERE id = %s", (user_id,)).fetchone()


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


# ---------- routes ----------
@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, conn: Conn) -> LoginResponse:
    user = find_user_by_credentials(conn, body.email, body.password)
    if user is None:
        raise ApiError("INVALID_CREDENTIALS", "Email or password is incorrect.", 401)
    return LoginResponse(token=issue_token(user["id"]), user=UserOut(**user))
