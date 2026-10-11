"""Floor endpoints (Act 1). Reads: any signed-in user. State changes: floor supervisor (owner always)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.auth import Conn, CurrentUser, require_permission
from app.modules.floor import service
from app.modules.floor.schemas import (FloorAvailability, FloorOutput, FloorProgress, MachineNow,
                                       StateChangeRequest, StateChangeResponse)

router = APIRouter(prefix="/api/floor", tags=["floor"])


@router.get("/machines", response_model=list[MachineNow])
def machines(conn: Conn, user: CurrentUser):
    return service.machines_now(conn)


@router.get("/output", response_model=FloorOutput)
def output(conn: Conn, user: CurrentUser, day: date | None = None):
    return service.output(conn, day)


@router.get("/availability", response_model=FloorAvailability)
def availability(conn: Conn, user: CurrentUser,
                 from_: Annotated[datetime | None, Query(alias="from")] = None,
                 to: datetime | None = None):
    return service.availability(conn, from_, to)


@router.get("/progress", response_model=FloorProgress)
def progress(conn: Conn, user: CurrentUser, at: datetime | None = None):
    return service.progress(conn, at)


@router.post("/machines/{code}/state", response_model=StateChangeResponse)
def change_state(body: StateChangeRequest, conn: Conn,
                 code: Annotated[str, Path(max_length=40)],
                 user: dict = Depends(require_permission("floor.change_state"))):
    return service.change_state(conn, code, body.state, body.reason)
