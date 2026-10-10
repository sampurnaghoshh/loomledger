"""Inventory endpoints. Stock: any signed-in user. Masters + receipts: store (owner always)."""
from __future__ import annotations

from datetime import datetime

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response

from app.auth import Conn, CurrentUser, require_role
from app.listing import ListParams, Page
from app.modules.inventory import service
from app.modules.inventory.schemas import LowStock, Masters, ReceiptRequest, ReceiptResponse, StockRow, StockSnapshot

router = APIRouter(prefix="/api/inventory", tags=["inventory"])


@router.get("/masters", response_model=Masters)
def masters(conn: Conn, user: dict = Depends(require_role("store"))):
    return service.masters(conn)


@router.get("/stock/list", response_model=Page[StockRow])
def stock_page(conn: Conn, user: CurrentUser, query: ListParams,
               location_code: Annotated[str | None, Query(max_length=40)] = None,
               lot_kind: Literal["yarn", "greige", "finished"] | None = None,
               product_code: Annotated[str | None, Query(max_length=40)] = None):
    """Stock now, paged: ?sort=(-)location_code|lot_code|product_code|qty|lot_kind"""
    return service.page_stock(conn, query, {"location_code": location_code, "lot_kind": lot_kind, "product_code": product_code})


@router.get("/stock", response_model=StockSnapshot)
def stock(conn: Conn, user: CurrentUser, as_of: datetime | None = None):
    return service.stock(conn, as_of)


@router.get("/low-stock", response_model=list[LowStock])
def low_stock(conn: Conn, user: CurrentUser):
    return service.low_stock(conn)


@router.post("/receipts", response_model=ReceiptResponse, status_code=201)
def receive(body: ReceiptRequest, conn: Conn, response: Response,
            user: dict = Depends(require_role("store"))):
    result, created = service.receive_yarn(conn, body, user)
    if not created:
        response.status_code = 200      # idempotent replay: the original result
    return result
