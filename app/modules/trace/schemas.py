"""Trace schemas. Field names = contract keys (trace_find_cause.json, trace_graph_*.json)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

LotKind = Literal["yarn", "greige", "finished"]


class CauseFactor(BaseModel):
    factor_kind: Literal["yarn_lot", "machine", "shift"]
    factor_label: str
    selected_covered: int
    selected_total: int
    inspected_through: int
    rejected_through: int
    rate_through_pct: float | None
    inspected_outside: int
    rejected_outside: int
    rate_outside_pct: float | None
    lift: float | None
    verdict: Literal["root_cause", "coincidental", "partial", "no_comparison"]


class FindCauseResponse(BaseModel):
    selected: list[str]
    factors: list[CauseFactor]          # ranked by find_cause(): factors[0] is the strongest candidate


class GraphNode(BaseModel):
    code: str
    kind: LotKind
    product: str
    qty: float
    uom: Literal["kg", "m"]
    status: Literal["active", "wip", "consumed", "dispatched", "quarantined", "recalled"]
    custody: str | None                 # null for yarn
    machine: str | None
    stage: Literal["spinning", "weaving", "dyeing", "finishing"] | None
    shift: str | None
    run_code: str | None
    produced_at: datetime
    supplier: str | None


class GraphEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(serialization_alias="from")
    to: str
    qty_consumed: float


class AncestorGraph(BaseModel):
    lot_codes: list[str]
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class DescendantGraph(BaseModel):
    lot_code: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class _LotCodes(BaseModel):
    lot_codes: list[str] = Field(min_length=1, max_length=500)

    @field_validator("lot_codes")
    @classmethod
    def distinct(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("a lot can only be listed once")
        return v


class FindCauseRequest(_LotCodes):
    pass


class GraphRequest(_LotCodes):
    direction: Literal["up", "down"] = "up"
