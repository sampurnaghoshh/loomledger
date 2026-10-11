"""Roll endpoints (QR passport + labels). Read-only: any signed-in user."""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query

from app.auth import Conn, CurrentUser
from app.listing import ListParams, Page
from app.modules.rolls import service
from app.modules.rolls.schemas import LOT_CODE, ROLL_CODE, Custody, LotStatus, RollLabels, RollListItem, RollPassport

router = APIRouter(prefix="/api/rolls", tags=["rolls"])


@router.get("", response_model=Page[RollListItem])
def rolls_page(conn: Conn, user: CurrentUser, query: ListParams,
               custody: Custody | None = None, status: LotStatus | None = None,
               kind: Literal["greige", "finished"] | None = None,
               qc_result: Literal["pass", "rework", "reject"] | None = None,
               order_code: Annotated[str | None, Query(max_length=40)] = None):
    """Every physical roll, paged: ?sort=(-)code|custody|status|qty_m|order_code|inspected_at|created_at"""
    return service.page_rolls(conn, query, {"custody": custody, "status": status, "kind": kind,
                                            "qc_result": qc_result, "order_code": order_code})


@router.get("/labels", response_model=RollLabels)
def labels(conn: Conn, user: CurrentUser,
           root: Annotated[str | None, Query(max_length=40, pattern=LOT_CODE)] = None):
    return service.labels(conn, root)


@router.get("/{code}/passport", response_model=RollPassport)
def passport(conn: Conn, user: CurrentUser, code: Annotated[str, Path(max_length=40, pattern=ROLL_CODE)]):
    return service.passport(conn, code)
