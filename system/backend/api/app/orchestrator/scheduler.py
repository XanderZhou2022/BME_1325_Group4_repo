from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from agents.clinical_summary.service import evaluate_clinical_summary
from agents.intervention_tracker.service import evaluate_due_pending_interventions
from agents.risk_sentinel.schemas import RiskSentinelEvaluateRequest
from agents.risk_sentinel.service import evaluate_risk_sentinel
from agents.ward_coordinator.schemas import WardCoordinatorEvaluateRequest
from agents.ward_coordinator.service import evaluate_ward
from app.config import get_settings

logger = logging.getLogger(__name__)


def _active_admissions(conn: psycopg.Connection) -> list[str]:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute("SELECT admission_id FROM admissions WHERE status = 'active' ORDER BY admit_time DESC")
        return [r["admission_id"] for r in cur.fetchall()]


def run_scheduler_tick() -> dict[str, int]:
    settings = get_settings()
    with psycopg.connect(settings.pg_dsn) as conn:
        due_count = evaluate_due_pending_interventions(conn, limit=100)
        admissions = _active_admissions(conn)
        risk_count = 0
        summary_count = 0
        for admission_id in admissions:
            try:
                risk = evaluate_risk_sentinel(conn, RiskSentinelEvaluateRequest(admission_id=admission_id, max_events=200))
                risk_count += 1
                if risk.escalation_level in ("warning", "critical"):
                    evaluate_clinical_summary(conn, admission_id)
                    summary_count += 1
            except Exception as exc:  # pragma: no cover - best effort periodic tasks
                logger.warning("scheduler risk tick failed for %s: %s", admission_id, exc)
        try:
            evaluate_ward(conn, WardCoordinatorEvaluateRequest(top_k=10))
        except Exception as exc:  # pragma: no cover
            logger.warning("scheduler ward tick failed: %s", exc)
    return {
        "pending_evaluated": due_count,
        "risk_runs": risk_count,
        "summary_runs": summary_count,
        "tick_ts": int(datetime.now(timezone.utc).timestamp()),
    }


async def scheduler_loop() -> None:
    settings = get_settings()
    while True:
        try:
            stats = run_scheduler_tick()
            logger.info("scheduler tick: %s", stats)
        except Exception as exc:  # pragma: no cover
            logger.error("scheduler tick error: %s", exc)
        await asyncio.sleep(max(10, settings.scheduler_interval_seconds))
