from __future__ import annotations

from fastapi import APIRouter, Depends
from psycopg import Connection

from app.db import get_db

from .schemas import CompassionDraftRequest, CompassionDraftResponse
from .service import evaluate_compassion_draft

router = APIRouter(prefix="/agents/compassion-family", tags=["agents"])


@router.post("/draft", response_model=CompassionDraftResponse)
def draft_family_communication(req: CompassionDraftRequest, conn: Connection = Depends(get_db)) -> CompassionDraftResponse:
    return evaluate_compassion_draft(conn, req)
