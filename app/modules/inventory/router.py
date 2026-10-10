"""Inventory endpoints. Stock: any signed-in user. Masters + receipts: store (owner always)."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Response

from app.auth import Conn, CurrentUser, require_role
from app.modules.inventory import service
from app.modules.inventory.schemas import Masters, ReceiptRequest, ReceiptResponse, StockSnapshot

router = APIRouter(prefix="/api/inventory", tags=["inventory"])


@router.get("/masters", response_model=Masters)
def masters(conn: Conn, user: dict = Depends(require_role("store"))):
    return service.masters(conn)


@router.get("/stock", response_model=StockSnapshot)
def stock(conn: Conn, user: CurrentUser, as_of: datetime | None = None):
    return service.stock(conn, as_of)


@router.post("/receipts", response_model=ReceiptResponse, status_code=201)
def receive(body: ReceiptRequest, conn: Conn, response: Response,
            user: dict = Depends(require_role("store"))):
    result, created = service.receive_yarn(conn, body, user)
    if not created:
        response.status_code = 200      # idempotent replay: the original result
    return result
