"""Recall endpoints (Acts 3–4). Preview: any signed-in user. Apply: qc (owner always)."""
from __future__ import annotations

from typing import Annotated, Union

from fastapi import APIRouter, Depends, Query, Response

from app.auth import Conn, CurrentUser, require_permission
from app.modules.recalls import service
from app.modules.recalls.schemas import ApplyRecallRequest, RecallApplied, RecallPreview

router = APIRouter(prefix="/api/recalls", tags=["recalls"])


@router.get("/preview", response_model=Union[RecallApplied, RecallPreview])
def preview(conn: Conn, user: CurrentUser, lot_code: Annotated[str, Query(min_length=1, max_length=40)]):
    return service.preview(conn, lot_code)


@router.post("", response_model=RecallApplied, status_code=201)
def apply(body: ApplyRecallRequest, conn: Conn, response: Response,
          user: dict = Depends(require_permission("recalls.apply"))):
    result, created = service.apply(conn, body.lot_code, body.reason, user)
    if not created:
        response.status_code = 200      # already recalled: the same recall, unchanged
    return result
