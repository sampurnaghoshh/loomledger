"""Orders (any signed-in user), dispatches (store; owner always), and the PUBLIC buyer track page."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app.auth import Conn, CurrentUser, require_role
from app.modules.orders import service
from app.modules.orders.schemas import BuyerOrderStatus, DispatchRequest, DispatchResponse, OrderSummary, YarnCheck

router = APIRouter(tags=["orders"])


@router.get("/api/orders", response_model=list[OrderSummary])
def list_orders(conn: Conn, user: CurrentUser):
    return service.list_orders(conn)


@router.get("/api/orders/{code}/yarn-check", response_model=YarnCheck)
def yarn_check(code: str, conn: Conn, user: CurrentUser):
    return service.yarn_check(conn, code)


@router.post("/api/dispatches", response_model=DispatchResponse, status_code=201)
def dispatch(body: DispatchRequest, conn: Conn, response: Response,
             user: dict = Depends(require_role("store"))):
    result, created = service.dispatch(conn, body, user)
    if not created:
        response.status_code = 200      # idempotent replay: the original result
    return result


@router.get("/api/track/{token}", response_model=BuyerOrderStatus)
def track(conn: Conn, token: str):
    """No login: the unguessable token in the link is the credential."""
    return service.track(conn, token)
