"""Quality endpoints. Lists: any signed-in user. Inspections: qc (owner always)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app.auth import Conn, CurrentUser, require_role
from app.modules.quality import service
from app.modules.quality.schemas import InspectionRequest, InspectionResponse, QueueItem, Rejection

router = APIRouter(prefix="/api/quality", tags=["quality"])


@router.get("/queue", response_model=list[QueueItem])
def queue(conn: Conn, user: CurrentUser):
    return service.queue(conn)


@router.get("/rejections", response_model=list[Rejection])
def rejections(conn: Conn, user: CurrentUser):
    return service.rejections(conn)


@router.post("/inspections", response_model=InspectionResponse, status_code=201)
def inspect(body: InspectionRequest, conn: Conn, response: Response,
            user: dict = Depends(require_role("qc"))):
    result, created = service.inspect(conn, body, user)
    if not created:
        response.status_code = 200      # idempotent replay of a rejection: the original result
    return result
