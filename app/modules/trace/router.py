"""Trace endpoints (Act 2). Read-only: any signed-in user."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path

from app.auth import Conn, CurrentUser
from app.modules.trace import service
from app.modules.trace.schemas import (AncestorGraph, DescendantGraph, FindCauseRequest, FindCauseResponse,
                                       GraphRequest)

router = APIRouter(prefix="/api/trace", tags=["trace"])


@router.post("/find-cause", response_model=FindCauseResponse)
def find_cause(body: FindCauseRequest, conn: Conn, user: CurrentUser):
    return service.find_cause(conn, body.lot_codes)


@router.post("/graph", response_model=AncestorGraph)
def graph(body: GraphRequest, conn: Conn, user: CurrentUser):
    return service.graph(conn, body.lot_codes, body.direction)


@router.get("/lots/{code}/descendants", response_model=DescendantGraph)
def descendants(conn: Conn, user: CurrentUser, code: Annotated[str, Path(max_length=40)]):
    return service.descendants(conn, code)
