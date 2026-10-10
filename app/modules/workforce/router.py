"""Workforce endpoints. Register: floor supervisor. Wages: accounts. (Owner always.)"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response

from app.auth import Conn, require_role
from app.listing import ListParams, Page
from app.modules.workforce import service
from app.modules.workforce.schemas import MarkRequest, MarkResponse, Register, Wages, WorkerRow

router = APIRouter(prefix="/api/workforce", tags=["workforce"])
Supervisor = Annotated[dict, Depends(require_role("floor_supervisor"))]


@router.get("/attendance", response_model=Register)
def register(conn: Conn, user: Supervisor, day: date | None = None):
    return service.register(conn, day)


@router.post("/attendance", response_model=MarkResponse, status_code=201)
def mark(body: MarkRequest, conn: Conn, response: Response, user: Supervisor):
    result, created = service.mark(conn, body, user)
    if not created:
        response.status_code = 200      # idempotent replay: the original result
    return result


@router.get("/wages", response_model=Wages)
def wages(conn: Conn, user: dict = Depends(require_role("accounts")),
          from_: Annotated[date | None, Query(alias="from")] = None, to: date | None = None):
    return service.wages(conn, from_, to)


@router.get("/workers", response_model=Page[WorkerRow])
def workers_page(conn: Conn, user: Supervisor, query: ListParams,
                 skill: Literal["spinning", "weaving", "dyeing", "finishing"] | None = None,
                 active: bool | None = None):
    """Workers, paged: ?sort=(-)code|full_name|hourly_wage|skill"""
    return service.page_workers(conn, query, {"skill": skill, "active": active})
