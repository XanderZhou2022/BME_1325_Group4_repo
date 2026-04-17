from __future__ import annotations

from fastapi import APIRouter, Depends
from psycopg import Connection
from psycopg.rows import dict_row

from app.db import get_db

from .schemas import DemoRunRequest, DemoRunResponse
from .service import run_demo_pipeline

router = APIRouter(prefix="/orchestrator", tags=["orchestrator"])


@router.post("/demo-run", response_model=DemoRunResponse)
def demo_run(request: DemoRunRequest, conn: Connection = Depends(get_db)) -> DemoRunResponse:
    return run_demo_pipeline(conn, request)


@router.get("/runs")
def list_runs(limit: int = 20, conn: Connection = Depends(get_db)):
    limit = max(1, min(limit, 200))
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT run_id, started_at, finished_at, target_admissions
            FROM orchestrator_runs
            ORDER BY started_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return cur.fetchall()


@router.get("/runs/{run_id}")
def get_run(run_id: str, conn: Connection = Depends(get_db)):
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT run_id, started_at, finished_at, target_admissions, step_results
            FROM orchestrator_runs
            WHERE run_id = %s
            """,
            (run_id,),
        )
        return cur.fetchone()

