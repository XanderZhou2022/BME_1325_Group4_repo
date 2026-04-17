from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, cast

from fastapi import HTTPException
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.services.ids import new_id

from .schemas import RiskImage, RiskSentinelEvaluateRequest, RiskSentinelEvaluateResponse, RiskSeverity


RISK_TO_ALERT_TYPE: dict[str, str] = {
    "shock": "shock_risk",
    "respiratory_failure": "resp_failure_risk",
    "persistent_hypoperfusion": "poor_fluid_response",
}

SEVERITY_ORDER = {"low": 0, "warning": 1, "critical": 2}
SEVERITY_TO_ESCALATION = {"low": "info", "warning": "warning", "critical": "critical"}
SEVERITY_TO_CONFIDENCE = {"low": Decimal("0.65"), "warning": Decimal("0.82"), "critical": Decimal("0.93")}


def _json_safe_risks(risks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for risk in risks:
        item = dict(risk)
        conf = item.get("confidence")
        if isinstance(conf, Decimal):
            item["confidence"] = float(conf)
        out.append(item)
    return out


def _calculate_risk_from_payloads(
    *,
    bedside_payload: dict[str, Any],
    intervention_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    abnormal_flags = list(bedside_payload.get("abnormal_flags") or [])
    trend_labels = list(bedside_payload.get("trend_labels") or [])
    urgency = str(bedside_payload.get("urgency_level") or "info")
    response_assessment = str(intervention_payload.get("response_assessment") or "")
    intervention_type = str(intervention_payload.get("intervention_type") or "")
    poor_response = response_assessment in ("non_responsive", "deteriorating_despite_intervention")

    risks: list[dict[str, Any]] = []
    if "persistent_hypotension" in abnormal_flags or (intervention_type in ("fluid", "vasopressor") and poor_response):
        severity = "critical" if poor_response or urgency == "critical" else "warning"
        risks.append(
            {
                "risk_type": "shock",
                "severity": severity,
                "confidence": SEVERITY_TO_CONFIDENCE[severity],
                "evidence": [{"source": "bedside", "abnormal_flags": abnormal_flags}, {"source": "intervention", "response_assessment": response_assessment}],
                "time_window": str(bedside_payload.get("analysis_window") or "latest"),
                "recommended_action": "review fluid response and source control",
            }
        )

    if "hypoxemia" in abnormal_flags or (intervention_type == "ventilator_change" and poor_response):
        severity = "critical" if poor_response else "warning"
        risks.append(
            {
                "risk_type": "respiratory_failure",
                "severity": severity,
                "confidence": SEVERITY_TO_CONFIDENCE[severity],
                "evidence": [{"source": "bedside", "trend_labels": trend_labels}, {"source": "intervention", "response_assessment": response_assessment}],
                "time_window": str(bedside_payload.get("analysis_window") or "latest"),
                "recommended_action": "reassess ventilator settings and gas exchange",
            }
        )

    if "oliguria" in abnormal_flags or ("persistent_hypotension" in abnormal_flags and poor_response):
        severity = "critical" if poor_response else "warning"
        risks.append(
            {
                "risk_type": "persistent_hypoperfusion",
                "severity": severity,
                "confidence": SEVERITY_TO_CONFIDENCE[severity],
                "evidence": [{"source": "bedside", "abnormal_flags": abnormal_flags}, {"source": "intervention", "response_assessment": response_assessment}],
                "time_window": str(bedside_payload.get("analysis_window") or "latest"),
                "recommended_action": "monitor post-fluid hemodynamic response",
            }
        )

    uniq: dict[str, dict[str, Any]] = {}
    for risk in risks:
        risk_type = str(risk["risk_type"])
        if risk_type not in uniq or SEVERITY_ORDER[str(risk["severity"])] > SEVERITY_ORDER[str(uniq[risk_type]["severity"])]:
            uniq[risk_type] = risk
    return list(uniq.values())


def evaluate_risk_sentinel(conn: Connection, req: RiskSentinelEvaluateRequest) -> RiskSentinelEvaluateResponse:
    with conn.transaction():
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT patient_id, bed_id
                FROM admissions
                WHERE admission_id = %s
                """,
                (req.admission_id,),
            )
            admission = cur.fetchone()
            if not admission:
                raise HTTPException(status_code=404, detail="Admission not found")
            patient_id = cast(str, admission["patient_id"])
            bed_id = cast(str, admission["bed_id"])

            cur.execute(
                """
                INSERT INTO agent_registry (agent_name, input_event_types, output_event_type, schema_version, enabled)
                VALUES ('risk_sentinel', '["bedside_analysis_ready","intervention_evaluation_ready","patient_memory_ready"]'::jsonb, 'risk_assessment_ready', 'v1', TRUE)
                ON CONFLICT (agent_name) DO UPDATE SET enabled = TRUE, updated_at = NOW()
                """
            )

            last_event_at = None
            if not req.force_recompute:
                cur.execute(
                    """
                    SELECT last_event_at
                    FROM agent_consumption_cursor
                    WHERE consumer_agent = 'risk_sentinel' AND admission_id = %s
                    """,
                    (req.admission_id,),
                )
                cursor_row = cur.fetchone()
                if cursor_row:
                    last_event_at = cursor_row["last_event_at"]

            cur.execute(
                """
                SELECT event_id, producer_agent, produced_at, payload
                FROM agent_events
                WHERE admission_id = %s
                  AND producer_agent = ANY(%s)
                  AND (%s::timestamptz IS NULL OR produced_at > %s::timestamptz)
                ORDER BY produced_at ASC, event_id ASC
                LIMIT %s
                """,
                (req.admission_id, ["bedside_monitor", "intervention_tracker", "patient_memory"], last_event_at, last_event_at, req.max_events),
            )
            events = cur.fetchall()

            consumed_event_ids = [cast(str, e["event_id"]) for e in events]

            cur.execute(
                """
                SELECT payload
                FROM agent_outputs
                WHERE admission_id = %s AND agent_name = 'bedside_monitor'
                ORDER BY generated_at DESC
                LIMIT 1
                """,
                (req.admission_id,),
            )
            bedside_row = cur.fetchone()
            bedside_payload = cast(dict[str, Any], (bedside_row["payload"] if bedside_row else {}))

            cur.execute(
                """
                SELECT payload
                FROM agent_outputs
                WHERE admission_id = %s AND agent_name = 'intervention_tracker'
                ORDER BY generated_at DESC
                LIMIT 1
                """,
                (req.admission_id,),
            )
            intv_row = cur.fetchone()
            intervention_payload = cast(dict[str, Any], (intv_row["payload"] if intv_row else {}))

            risks = _calculate_risk_from_payloads(bedside_payload=bedside_payload, intervention_payload=intervention_payload)

            for risk in risks:
                risk_id = new_id("risk")
                cur.execute(
                    """
                    INSERT INTO risk_assessments (
                        id, admission_id, timestamp, risk_type, confidence, severity, evidence, time_window, recommended_action
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                    """,
                    (
                        risk_id,
                        req.admission_id,
                        datetime.now(timezone.utc),
                        risk["risk_type"],
                        risk["confidence"],
                        risk["severity"],
                        Json(risk["evidence"]),
                        risk["time_window"],
                        risk["recommended_action"],
                    ),
                )

                alert_id = new_id("alert")
                cur.execute(
                    """
                    INSERT INTO alerts (
                        alert_id, admission_id, patient_id, bed_id, alert_type, severity, status,
                        source_agent, evidence, first_seen_at, last_seen_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, 'open', 'risk_sentinel', %s::jsonb, %s, %s)
                    """,
                    (
                        alert_id,
                        req.admission_id,
                        patient_id,
                        bed_id,
                        RISK_TO_ALERT_TYPE.get(str(risk["risk_type"]), f"{risk['risk_type']}_risk"),
                        "critical" if risk["severity"] == "critical" else "warning",
                        Json(risk["evidence"]),
                        datetime.now(timezone.utc),
                        datetime.now(timezone.utc),
                    ),
                )

            active_risks = [{"risk_type": r["risk_type"], "severity": r["severity"]} for r in risks]
            if active_risks:
                max_sev = max(active_risks, key=lambda x: SEVERITY_ORDER[str(x["severity"])])["severity"]
                care_phase = "critical" if max_sev == "critical" else "unstable"
                cur.execute(
                    """
                    UPDATE patient_state_current
                    SET active_risks = %s::jsonb, care_phase = %s, updated_at = NOW()
                    WHERE admission_id = %s
                    """,
                    (Json(active_risks), care_phase, req.admission_id),
                )

            payload = {
                "risks": _json_safe_risks(risks),
                "consumed_event_ids": consumed_event_ids,
            }
            output_id = new_id("out")
            event_id = new_id("aevt")
            cur.execute(
                """
                INSERT INTO agent_outputs (
                    output_id, admission_id, patient_id, bed_id, agent_name,
                    schema_version, output_type, generated_at, payload
                ) VALUES (%s, %s, %s, %s, 'risk_sentinel', 'v1', 'risk_assessment_ready', %s, %s::jsonb)
                """,
                (output_id, req.admission_id, patient_id, bed_id, datetime.now(timezone.utc), Json(payload)),
            )
            cur.execute(
                """
                INSERT INTO agent_events (
                    event_id, admission_id, patient_id, bed_id, producer_agent,
                    event_type, schema_version, produced_at, output_id, payload
                ) VALUES (%s, %s, %s, %s, 'risk_sentinel', 'risk_assessment_ready', 'v1', %s, %s, %s::jsonb)
                """,
                (event_id, req.admission_id, patient_id, bed_id, datetime.now(timezone.utc), output_id, Json(payload)),
            )

            if events:
                last = events[-1]
                cur.execute(
                    """
                    INSERT INTO agent_consumption_cursor (
                        consumer_agent, admission_id, last_event_id, last_event_at, updated_at
                    ) VALUES ('risk_sentinel', %s, %s, %s, NOW())
                    ON CONFLICT (consumer_agent, admission_id) DO UPDATE SET
                        last_event_id = EXCLUDED.last_event_id,
                        last_event_at = EXCLUDED.last_event_at,
                        updated_at = NOW()
                    """,
                    (req.admission_id, last["event_id"], last["produced_at"]),
                )

    if risks:
        highest = max(risks, key=lambda r: SEVERITY_ORDER[str(r["severity"])])
        escalation = cast(str, SEVERITY_TO_ESCALATION[str(highest["severity"])])
    else:
        escalation = "info"
    return RiskSentinelEvaluateResponse(
        admission_id=req.admission_id,
        consumed_event_count=len(consumed_event_ids),
        consumed_event_ids=consumed_event_ids,
        risks=[
            RiskImage(
                risk_type=str(r["risk_type"]),
                confidence=cast(Decimal, r["confidence"]),
                severity=cast(RiskSeverity, str(r["severity"])),
                evidence=cast(list[dict[str, Any]], r["evidence"]),
                time_window=str(r["time_window"]),
                recommended_action=str(r["recommended_action"]),
            )
            for r in risks
        ],
        escalation_level=cast(Any, escalation),
        generated_at=datetime.now(timezone.utc),
    )
