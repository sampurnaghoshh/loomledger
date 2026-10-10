"""Production endpoints. Floor supervisor (owner always)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response

from app.auth import Conn, require_role
from app.modules.production import service
from app.modules.production.schemas import (FinishWeavingRequest, FinishWeavingResponse, StartWeavingRequest,
                                            StartWeavingResponse)

router = APIRouter(prefix="/api/production", tags=["production"])
Supervisor = Annotated[dict, Depends(require_role("floor_supervisor"))]


@router.post("/weaving-runs", response_model=StartWeavingResponse, status_code=201)
def start_weaving(body: StartWeavingRequest, conn: Conn, response: Response, user: Supervisor):
    result, created = service.start_weaving(conn, body, user)
    if not created:
        response.status_code = 200      # idempotent replay: the original result
    return result


@router.post("/weaving-runs/{run_code}/finish", response_model=FinishWeavingResponse)
def finish_weaving(body: FinishWeavingRequest, conn: Conn, user: Supervisor,
                   run_code: Annotated[str, Path(max_length=40)]):
    return service.finish_weaving(conn, run_code, body, user)
