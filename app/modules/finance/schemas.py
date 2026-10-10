"""Finance schemas. Field names = contract keys (finance_mass_balance.json, finance_roll_costs_*.json, finance_pnl*.json)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BalanceTotals(BaseModel):
    received_kg: float
    issued_kg: float
    fabric_kg: float
    waste_kg: float
    wip_kg: float
    unaccounted_kg: float
    unaccounted_pct: float | None        # null when nothing was issued in the window


class MachineUnaccounted(BaseModel):
    machine_code: str
    machine_name: str
    runs: int
    issued_kg: float
    unaccounted_kg: float
    unaccounted_pct: float | None


class MassBalance(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: datetime | None = Field(serialization_alias="from")    # null = all time
    to: datetime | None
    first_run_at: datetime | None         # earliest weaving run in the window; null when there are none
    totals: BalanceTotals
    by_machine: list[MachineUnaccounted]  # worst first


class RollCost(BaseModel):
    lot_code: str
    qty_m: float
    material: float
    machine: float
    labour: float
    chemicals: float
    total: float
    cost_per_m: float
    custody: Literal["consumed", "at_customer", "wip", "rejected", "rework", "passed_in_store", "awaiting_qc"]
    status: Literal["active", "wip", "consumed", "dispatched", "quarantined", "recalled"]


# ---------------------------------------------------------------- monthly P&L (migration 013, finance_pnl*.json)
class Accrual(BaseModel):
    invoices: int
    rolls_invoiced: int
    revenue: float                       # invoices issued in the period
    material: float                      # lot_cost() of the invoiced rolls: yarn ...
    machine: float                       # ... machine hours ...
    chemicals: float                     # ... and dye chemicals
    cost_of_goods_sold: float            # material + machine + chemicals (labour is NOT in here ...)
    labour_in_lot_cost_excluded: float   # ... lot_cost's labour, left out so it is not counted twice
    wages: float                         # ... labour enters once, as the period's wages()
    profit: float                        # revenue - cost_of_goods_sold - wages


class Cash(BaseModel):
    received_from_buyers: float
    yarn_bills_paid: float
    wages_paid: float
    wages_paid_basis: str                # "assumed paid as earned" (no payroll ledger)
    net_cash: float


class Receivable(BaseModel):
    buyer_code: str
    buyer: str
    invoices: int
    outstanding: float


class Payable(BaseModel):
    supplier_code: str
    supplier: str
    bills: int
    outstanding: float


class RecallExposure(BaseModel):
    recall_code: str
    lot_code: str
    applied_at: datetime
    total_exposure: float
    cost_already_incurred: float
    recall_exposure: float
    quarantined_material_value: float


class Pnl(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: date = Field(serialization_alias="from")    # both ends inclusive, mill dates
    to: date
    accrual: Accrual
    cash: Cash
    receivables: list[Receivable]        # as of `to`, largest first
    receivables_total: float
    payables: list[Payable]
    payables_total: float
    recalls: list[RecallExposure]        # applied in the period: contingent, not subtracted from profit


class PaymentRequest(BaseModel):
    invoice_code: str = Field(pattern=r"^INV-\d{4}-\d+$")
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    method: Literal["bank_transfer", "cheque", "upi", "cash"]
    idempotency_key: str = Field(min_length=8, max_length=100)


class PaymentResponse(BaseModel):
    payment_id: int
    invoice_code: str
    amount: float
    method: str
    paid_at: datetime
    invoice_amount: float
    outstanding_after: float             # what was still due right after this payment


class InvoiceRow(BaseModel):
    code: str
    order_code: str
    buyer: str
    dispatch_code: str
    dispatched_at: datetime
    rolls: int
    amount: float
    paid: float
    outstanding: float
    issued_at: datetime
