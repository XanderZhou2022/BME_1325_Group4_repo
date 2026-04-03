from __future__ import annotations

import psycopg

from app.config import get_settings

# Ensure `agents.*` can be imported and share path injection is applied.
from app.main import app  # noqa: F401

from agents.bedside_monitor.schemas import BedsideAnalyzeRequest
from agents.bedside_monitor.service import analyze_bedside
from agents.intervention_tracker.schemas import InterventionEvaluateRequest
from agents.intervention_tracker.service import evaluate_intervention_tracker
from agents.risk_sentinel.schemas import RiskSentinelEvaluateRequest
from agents.risk_sentinel.service import evaluate_risk_sentinel


def main() -> None:
    settings = get_settings()
    admission_id = "adm1"
    intervention_id = "intv1"

    conn = psycopg.connect(settings.pg_dsn)
    try:
        print(f"[manual-acceptance] admission_id={admission_id} intervention_id={intervention_id}")

        bedside_out = analyze_bedside(conn, BedsideAnalyzeRequest(admission_id=admission_id, analysis_window="last_4h"))
        print("[bedside] urgency=", bedside_out.urgency_level, "abnormal_flags=", bedside_out.abnormal_flags)

        intervention_out = evaluate_intervention_tracker(
            conn,
            InterventionEvaluateRequest(admission_id=admission_id, intervention_id=intervention_id),
        )
        print(
            "[intervention] type=",
            intervention_out.intervention_type,
            "assessment=",
            intervention_out.response_assessment,
        )

        risk_out = evaluate_risk_sentinel(conn, RiskSentinelEvaluateRequest(admission_id=admission_id))
        print("[risk-sentinel] escalation_level=", risk_out.escalation_level)
        for r in risk_out.risks:
            print("  - risk_type=", r.risk_type, "severity=", r.severity, "confidence=", r.confidence)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT timestamp, state_snapshot
                FROM patient_state_snapshots
                WHERE admission_id = %s
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (admission_id,),
            )
            ts, ss = cur.fetchone()
            shared = ss.get("shared_patient_state_board") if isinstance(ss, dict) else None
            print("[db-check] latest snapshot ts=", ts)
            print("[db-check] shared_patient_state_board keys=" , list(shared.keys()) if isinstance(shared, dict) else shared)

            cur.execute(
                """
                SELECT risk_type, severity, confidence, recommended_action
                FROM risk_assessments
                WHERE admission_id = %s
                ORDER BY timestamp DESC
                LIMIT 5
                """,
                (admission_id,),
            )
            print("[db-check] latest risk_assessments:")
            for row in cur.fetchall():
                print(" ", row)

            cur.execute(
                """
                SELECT alert_type, severity, status, source_agent
                FROM alerts
                WHERE admission_id = %s
                ORDER BY last_seen_at DESC
                LIMIT 5
                """,
                (admission_id,),
            )
            print("[db-check] latest alerts:")
            for row in cur.fetchall():
                print(" ", row)

    finally:
        conn.close()


if __name__ == "__main__":
    main()

