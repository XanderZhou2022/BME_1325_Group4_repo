from __future__ import annotations

from datetime import datetime, timezone

from psycopg import Connection
from psycopg.rows import dict_row

from .schemas import WardBedPriority, WardCoordinatorEvaluateRequest, WardCoordinatorEvaluateResponse

PHASE_SCORE = {"critical": 100, "unstable": 60, "stable": 20}
RISK_SCORE = {"critical": 40, "warning": 20, "low": 10}


def evaluate_ward(conn: Connection, req: WardCoordinatorEvaluateRequest) -> WardCoordinatorEvaluateResponse:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT admission_id, patient_id, bed_id, care_phase, active_risks
            FROM patient_state_current
            ORDER BY updated_at DESC
            """
        )
        rows = cur.fetchall()

    queue: list[WardBedPriority] = []
    alert_summary = {"critical": 0, "warning": 0, "info": 0}

    for r in rows:
        risks = r["active_risks"] or []
        max_risk_score = 0
        max_risk_label = "none"
        for risk in risks:
            sev = str((risk or {}).get("severity") or "low")
            if sev == "critical":
                alert_summary["critical"] += 1
            elif sev == "warning":
                alert_summary["warning"] += 1
            else:
                alert_summary["info"] += 1
            score = RISK_SCORE.get(sev, 0)
            if score > max_risk_score:
                max_risk_score = score
                max_risk_label = sev

        phase = str(r["care_phase"])
        score = PHASE_SCORE.get(phase, 0) + max_risk_score
        reason = f"care_phase={phase}, max_risk={max_risk_label}"
        queue.append(
            WardBedPriority(
                admission_id=r["admission_id"],
                patient_id=r["patient_id"],
                bed_id=r["bed_id"],
                care_phase=phase,
                priority_score=score,
                reason=reason,
            )
        )

    queue.sort(key=lambda x: x.priority_score, reverse=True)
    top = queue[: req.top_k]

    if alert_summary["critical"] >= 5:
        load = "high"
    elif alert_summary["critical"] >= 2 or alert_summary["warning"] >= 5:
        load = "medium"
    else:
        load = "normal"

    pending = [f"review_{item.bed_id}" for item in top[:3]]
    return WardCoordinatorEvaluateResponse(
        generated_at=datetime.now(timezone.utc),
        active_admission_count=len(rows),
        priority_queue=top,
        pending_actions=pending,
        ward_load_indicator=load,
        alert_storm_summary=alert_summary,
    )
