"""Validation log: owner and qc (permission validation_log.view, 017)."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth import Conn, require_permission
from app.listing import ListParams, Page
from app.modules.validation import service
from app.modules.validation.schemas import ValidationLogRow

router = APIRouter(prefix="/api/validation-log", tags=["validation"])
Viewer = Annotated[dict, Depends(require_permission("validation_log.view"))]


@router.get("", response_model=Page[ValidationLogRow])
def validation_log(conn: Conn, user: Viewer, query: ListParams,
                   code: Annotated[str | None, Query(max_length=40, pattern=r"^[A-Z_]+$")] = None,
                   sqlstate: Annotated[str | None, Query(max_length=5)] = None,
                   user_email: Annotated[str | None, Query(alias="user", max_length=254)] = None,
                   since: datetime | None = None, before: datetime | None = None):
    """Newest first: ?code=PHASE_SKIPPED &user=qc@everest.test &since=2026-10-10 &before=… &q= &sort=(-)at|error_code|…"""
    return service.page(conn, query, {"code": code, "sqlstate": sqlstate, "user": user_email,
                                      "since": since, "before": before})
