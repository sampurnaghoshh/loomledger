"""One error envelope for every non-2xx response, and the SQLSTATE -> API code mapping.

Envelope (docs/API_CONTRACT.md):
    {"error": {"code", "message", "hint", "sqlstate", "fields"}}

The mapping table in API_CONTRACT.md is the source of truth; keep the two in sync.
Messages from our own RAISE EXCEPTIONs (LL0xx) are written for users and passed through.
Everything else gets a fixed message: no SQL text, no stack traces, no row data.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import psycopg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("loomledger.errors")

# Named constraints that deserve their own code (see 001_core.sql).
ONE_DISPATCH_PER_ROLL = "one_dispatch_per_roll"
IDEMPOTENCY_CONSTRAINTS = {"stock_move_idempotency_key_key"}


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int, hint: str | None = None,
                 fields: dict[str, str] | None = None, sqlstate: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.hint = hint
        self.fields = fields
        self.sqlstate = sqlstate

    def body(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "hint": self.hint,
                          "sqlstate": self.sqlstate, "fields": self.fields}}


def not_found(message: str = "Not found.") -> ApiError:
    return ApiError("NOT_FOUND", message, 404)


def is_idempotency_replay(exc: BaseException) -> bool:
    """True if `exc` is a duplicate idempotency_key — the service should return the original result (200)."""
    return (isinstance(exc, psycopg.errors.UniqueViolation)
            and exc.diag.constraint_name in IDEMPOTENCY_CONSTRAINTS)


_KEY_COLUMN = re.compile(r"^Key \(([^)]+)\)=")


def _key_column(exc: psycopg.Error) -> str | None:
    m = _KEY_COLUMN.match(exc.diag.message_detail or "")
    return m.group(1) if m else None


def map_db_error(exc: psycopg.Error) -> ApiError:
    """Translate a psycopg error into the contract's ApiError (by SQLSTATE, then constraint name)."""
    state = exc.sqlstate or ""
    diag = exc.diag
    constraint = diag.constraint_name

    # Our own business rules (002_ledger_guards.sql): the DB message is the user message.
    if state == "LL001":
        return ApiError("LOT_QUARANTINED", diag.message_primary or "Lot is quarantined.", 409,
                        hint=diag.message_hint or None, sqlstate=state)
    if state == "LL002":
        return ApiError("INSUFFICIENT_STOCK", diag.message_primary or "Insufficient stock.", 422,
                        hint=diag.message_hint or None, sqlstate=state)
    if state == "LL004":
        return ApiError("NOT_QC_PASSED", diag.message_primary or "Roll has not passed quality control.", 409,
                        hint=diag.message_hint or None, sqlstate=state)
    if state == "LL005":
        return ApiError("NOT_IN_ORDER", diag.message_primary or "Roll is not reserved for this order.", 422,
                        hint=diag.message_hint or None, sqlstate=state)
    if state == "LL003":
        return ApiError("LEDGER_IMMUTABLE", diag.message_primary or "The stock ledger is append-only.", 405,
                        hint="Post a correcting movement instead.", sqlstate=state)

    if state == "23P01":
        return ApiError("MACHINE_BUSY", "That machine is already booked for this time.", 409,
                        hint="Pick another machine or finish the running job first.", sqlstate=state)
    if state == "23505":
        if constraint == ONE_DISPATCH_PER_ROLL:
            return ApiError("ALREADY_DISPATCHED", "One or more rolls have already been dispatched.", 409,
                            sqlstate=state)
        if constraint in IDEMPOTENCY_CONSTRAINTS:
            # Services catch this with is_idempotency_replay(); reaching here means one didn't.
            return ApiError("DUPLICATE_REQUEST", "This request was already submitted.", 409, sqlstate=state)
        col = _key_column(exc) or constraint or "value"
        return ApiError("VALIDATION_FAILED", "A record with this value already exists.", 422,
                        fields={col: "already exists"}, sqlstate=state)
    if state == "23503":
        col = _key_column(exc) or constraint or "reference"
        return ApiError("VALIDATION_FAILED", "A referenced record does not exist or is still in use.", 422,
                        fields={col: "invalid reference"}, sqlstate=state)
    if state == "23514":
        return ApiError("VALIDATION_FAILED", "The data breaks a business rule.", 422,
                        fields={constraint or "check": "check failed"}, sqlstate=state)
    if state == "23502":
        return ApiError("VALIDATION_FAILED", "A required value is missing.", 422,
                        fields={diag.column_name or "value": "required"}, sqlstate=state)
    if state.startswith("23") or state.startswith("22"):
        # remaining integrity violations + data exceptions (bad enum text, out of range, invalid parameter)
        return ApiError("VALIDATION_FAILED", "The request contains invalid data.", 422, sqlstate=state)
    if state == "P0002":
        return ApiError("NOT_FOUND", "Not found.", 404, sqlstate=state)
    if state in ("40001", "40P01"):
        return ApiError("CONFLICT_RETRY", "Another change got there first. Please try again.", 409,
                        sqlstate=state)
    if state.startswith("08") or (isinstance(exc, psycopg.OperationalError) and not state):
        return ApiError("DB_UNAVAILABLE", "The database is unavailable. Please try again shortly.", 503,
                        sqlstate=state or None)
    return ApiError("INTERNAL", "Something went wrong on our side.", 500)


def _internal() -> JSONResponse:
    return JSONResponse(ApiError("INTERNAL", "Something went wrong on our side.", 500).body(), status_code=500)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    """Last resort: log the traceback with the request id, tell the client nothing about internals."""
    if isinstance(exc, ApiError):
        return JSONResponse(exc.body(), status_code=exc.status)
    if isinstance(exc, psycopg.Error):
        return _db_error_response(request, exc)
    log.exception("unhandled error rid=%s %s %s", _request_id(request), request.method, request.url.path,
                  exc_info=exc)
    return _internal()


def _db_error_response(request: Request, exc: psycopg.Error) -> JSONResponse:
    err = map_db_error(exc)
    if err.status >= 500:
        log.error("db error rid=%s sqlstate=%s %s", _request_id(request), exc.sqlstate, exc, exc_info=exc)
    return JSONResponse(err.body(), status_code=err.status)


_HTTP_CODES = {401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(exc.body(), status_code=exc.status)

    @app.exception_handler(psycopg.Error)
    async def _psycopg_error(request: Request, exc: psycopg.Error) -> JSONResponse:
        return _db_error_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields: dict[str, str] = {}
        for e in exc.errors():
            loc = [str(p) for p in e.get("loc", ()) if p not in ("body", "query", "path", "header")]
            fields.setdefault(".".join(loc) or "body", e.get("msg", "invalid"))
        err = ApiError("VALIDATION_FAILED", "Please correct the highlighted fields.", 422, fields=fields)
        return JSONResponse(err.body(), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "INTERNAL" if exc.status_code >= 500 else "BAD_REQUEST")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(ApiError(code, message, exc.status_code).body(), status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        return handle_unexpected(request, exc)
