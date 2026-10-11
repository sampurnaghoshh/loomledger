"""Orders (any signed-in user), dispatches (store; owner always), and the PUBLIC buyer track page."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from typing import Annotated, Literal

from fastapi import Query

from app.auth import Conn, CurrentUser, require_permission
from app.listing import ListParams, Page
from app.modules.orders import service
from app.modules.orders.schemas import BuyerOrderStatus, DispatchRequest, DispatchResponse, OrderSummary, YarnCheck

router = APIRouter(tags=["orders"])


@router.get("/api/orders", response_model=list[OrderSummary])
def list_orders(conn: Conn, user: CurrentUser):
    return service.list_orders(conn)


@router.get("/api/orders/list", response_model=Page[OrderSummary])
def orders_page(conn: Conn, user: CurrentUser, query: ListParams,
                status: Literal["confirmed", "in_production", "partially_dispatched", "dispatched", "cancelled"] | None = None,
                buyer: Annotated[str | None, Query(max_length=100)] = None,
                yarn_status: Literal["ok", "short"] | None = None,
                late: bool | None = None):
    """Paged orders: ?page=&page_size=&q=&sort=(-)code|buyer|status|promised_date|revised_promise_date|delay_days|ordered_m"""
    return service.page_orders(conn, query, {"status": status, "buyer": buyer, "yarn_status": yarn_status, "late": late})


@router.get("/api/orders/{code}/yarn-check", response_model=YarnCheck)
def yarn_check(code: str, conn: Conn, user: CurrentUser):
    return service.yarn_check(conn, code)


@router.post("/api/dispatches", response_model=DispatchResponse, status_code=201)
def dispatch(body: DispatchRequest, conn: Conn, response: Response,
             user: dict = Depends(require_permission("orders.dispatch"))):
    result, created = service.dispatch(conn, body, user)
    if not created:
        response.status_code = 200      # idempotent replay: the original result
    return result


@router.get("/api/track/{token}", response_model=BuyerOrderStatus)
def track(conn: Conn, token: str):
    """No login: the unguessable token in the link is the credential."""
    return service.track(conn, token)
