"""Inventory schemas. Field names = contract keys (docs/api-mocks/inventory_*.json, types.ts ReceiptRequest)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class StockRow(BaseModel):
    location_code: str
    lot_code: str
    lot_kind: Literal["yarn", "greige", "finished"]
    product_code: str
    qty: float
    uom: Literal["kg", "m"]


class StockSnapshot(BaseModel):
    as_of: datetime | None          # null = now
    rows: list[StockRow]


class ReceiptRequest(BaseModel):
    supplier_code: str = Field(min_length=1, max_length=40)
    lot_code: str = Field(pattern=r"^Y-\d{3,}$")
    kg: float = Field(gt=0, le=100_000)
    price_per_kg: float = Field(gt=0, le=100_000)
    vehicle_no: str | None = Field(default=None, max_length=40)
    challan_no: str | None = Field(default=None, max_length=40)
    product_code: str | None = Field(default=None, max_length=40)   # omitted = the only yarn product
    idempotency_key: str = Field(min_length=8, max_length=100)


class CodeName(BaseModel):
    code: str
    name: str


class Masters(BaseModel):
    suppliers: list[CodeName]          # parties a yarn receipt can come from
    yarn_products: list[CodeName]      # what can be received (product_code on POST /receipts)


class ReceiptResponse(BaseModel):
    receipt_code: str
    lot_code: str
    kg: float
    location: str
