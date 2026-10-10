"""Quality endpoints. Lists: any signed-in user. Inspections: qc (owner always)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.auth import Conn, CurrentUser, require_role
from app.listing import ListParams, Page
from app.modules.quality import service
from app.modules.quality.schemas import InspectionRequest, InspectionResponse, LatestRejections, QueueItem, Rejection

router = APIRouter(prefix="/api/quality", tags=["quality"])


@router.get("/queue/list", response_model=Page[QueueItem])
def queue_page(conn: Conn, user: CurrentUser, query: ListParams,
               order_code: Annotated[str | None, Query(max_length=40)] = None,
               dyed_on: Annotated[str | None, Query(max_length=60)] = None):
    """Rolls awaiting QC, paged: ?sort=(-)lot_code|dyed_at|order_code|dye_batch"""
    return service.page_queue(conn, query, {"order_code": order_code, "dyed_on": dyed_on})


@router.get("/rejections/list", response_model=Page[Rejection])
def rejections_page(conn: Conn, user: CurrentUser, query: ListParams,
                    defect_type: Annotated[str | None, Query(max_length=60)] = None,
                    order_code: Annotated[str | None, Query(max_length=40)] = None,
                    inspector: Annotated[str | None, Query(max_length=100)] = None):
    """Every rejection, paged (newest first by default): ?sort=(-)inspected_at|lot_code|defect_type|inspector"""
    return service.page_rejections(conn, query, {"defect_type": defect_type, "order_code": order_code, "inspector": inspector})


@router.get("/queue", response_model=list[QueueItem])
def queue(conn: Conn, user: CurrentUser):
    return service.queue(conn)


@router.get("/latest-rejections", response_model=LatestRejections)
def latest_rejections(conn: Conn, user: CurrentUser):
    return service.latest_rejections(conn)


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
