"""Roll endpoints (QR passport + labels). Read-only: any signed-in user."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query

from app.auth import Conn, CurrentUser
from app.modules.rolls import service
from app.modules.rolls.schemas import LOT_CODE, ROLL_CODE, RollLabels, RollPassport

router = APIRouter(prefix="/api/rolls", tags=["rolls"])


@router.get("/labels", response_model=RollLabels)
def labels(conn: Conn, user: CurrentUser,
           root: Annotated[str | None, Query(max_length=40, pattern=LOT_CODE)] = None):
    return service.labels(conn, root)


@router.get("/{code}/passport", response_model=RollPassport)
def passport(conn: Conn, user: CurrentUser, code: Annotated[str, Path(max_length=40, pattern=ROLL_CODE)]):
    return service.passport(conn, code)
