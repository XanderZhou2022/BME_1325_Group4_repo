from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, cast

from fastapi import HTTPException
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.services.ids import new_id

from agents.risk_sentinel.rules import run_risk_sentinel
from agents.shared_patient_state_board.service import get_shared_board_from_latest_snapshot
from agents.risk_sentinel.schemas import (
    RiskImage,
    RiskSentinelEvaluateRequest,
    RiskSentinelEvaluateResponse,
    RiskSeverity,
)


RISK_TO_ALERT_TYPE: dict[str, str] = {
    "shock": "shock_risk",
    "respiratory_failure": "resp_failure_risk",
    "persistent_hypoperfusion": "poor_fluid_response",
}

RISK_SEVERITY_TO_ALERT_SEVERITY: dict[RiskSeverity, str] = {
    "low": "info",
    "warning": "warning",
    "critical": "critical",
}


def _insert_risk_assessments(
    conn: Connection,
    *,
    admission_id: str,
    risks: list[dict[str, Any]],
) -> None:
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        for r in risks:
            risk_id = new_id("risk")
            cur.execute(
                """
                INSERT INTO risk_assessments (
                    id, admission_id, timestamp,
                    risk_type, confidence, severity,
                    evidence, time_window, recommended_action
                ) VALUES (
                    %s, %s, %s,
                    %s, %s, %s,
                    %s::jsonb, %s, %s
                )
                """,
                (
                    risk_id,
                    admission_id,
                    now,
                    r["risk_type"],
                    r["confidence"],
                    r["severity"],
                    Json(r["evidence"]),
                    r["time_window"],
                    r["recommended_action"],
                ),
            )


def _insert_alerts(
    conn: Connection,
    *,
    admission_id: str,
    patient_id: str,
    bed_id: str,
    risks: list[dict[str, Any]],
    source_agent: str = "risk_sentinel",
) -> None:
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        for r in risks:
            risk_type = str(r["risk_type"])
            alert_type = RISK_TO_ALERT_TYPE.get(risk_type, f"{risk_type}_alert")
            severity = cast(RiskSeverity, str(r["severity"]))
            alert_sev = RISK_SEVERITY_TO_ALERT_SEVERITY[severity]

            alert_id = new_id("alert")
            cur.execute(
                """
                INSERT INTO alerts (
                    alert_id, admission_id, patient_id, bed_id,
                    alert_type, severity, status,
                    source_agent, evidence,
                    first_seen_at, last_seen_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, 'open',
                    %s, %s::jsonb,
                    %s, %s
                )
                """,
                (
                    alert_id,
                    admission_id,
                    patient_id,
                    bed_id,
                    alert_type,
                    alert_sev,
                    source_agent,
                    Json(r["evidence"]),
                    now,
                    now,
                ),
            )


def _update_active_risks(
    conn: Connection,
    *,
    admission_id: str,
    risks: list[dict[str, Any]],
    escalation_level: str,
) -> None:
    # Optional: keep patient_state_current.active_risks in sync.
    active_risks = [{"risk_type": r["risk_type"], "severity": r["severity"]} for r in risks]

    care_phase = "critical" if escalation_level == "critical" else "unstable"
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE patient_state_current
            SET active_risks = %s::jsonb,
                care_phase = %s
            WHERE admission_id = %s
            """,
            (Json(active_risks), care_phase, admission_id),
        )


def evaluate_risk_sentinel(
    conn: Connection,
    req: RiskSentinelEvaluateRequest,
) -> RiskSentinelEvaluateResponse:
    board = get_shared_board_from_latest_snapshot(conn, admission_id=req.admission_id)
    if not board:
        raise HTTPException(status_code=404, detail="No shared board snapshot found for admission_id")

    bedside_entry = board.get("bedside_monitor") or {}
    intervention_entry = board.get("intervention_tracker") or {}
    if not isinstance(bedside_entry, dict) or not isinstance(intervention_entry, dict):
        raise HTTPException(status_code=400, detail="Invalid shared board snapshot structure")

    bedside_structured_payload = cast(dict[str, Any], bedside_entry.get("structured_payload") or {})
    bedside_evidence = cast(list[dict[str, Any]], bedside_entry.get("evidence") or [])

    intervention_structured_payload = cast(dict[str, Any], intervention_entry.get("structured_payload") or {})
    intervention_evidence = cast(list[dict[str, Any]], intervention_entry.get("evidence") or [])

    # Run pure rules.
    res = run_risk_sentinel(
        bedside_structured_payload=bedside_structured_payload,
        bedside_evidence=bedside_evidence,
        intervention_structured_payload=intervention_structured_payload,
        intervention_evidence=intervention_evidence,
    )

    risks = cast(list[dict[str, Any]], res["risks"])
    escalation_level = cast(str, res["escalation_level"])

    if not risks:
        # Still return a valid response; do not write empty risks.
        return RiskSentinelEvaluateResponse(
            admission_id=req.admission_id,
            risks=[],
            escalation_level="info",
            generated_at=datetime.now(timezone.utc),
        )

    # Resolve patient/bed for alerts writing.
    patient_id = str(bedside_entry.get("patient_id") or intervention_entry.get("patient_id") or "")
    bed_id = str(bedside_entry.get("bed_id") or intervention_entry.get("bed_id") or "")
    if not patient_id or not bed_id:
        # Can happen if only one entry exists; fall back to admissions table lookup.
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT patient_id, bed_id FROM admissions WHERE admission_id = %s",
                (req.admission_id,),
            )
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Admission not found")
        patient_id = cast(str, row["patient_id"])
        bed_id = cast(str, row["bed_id"])

    _insert_risk_assessments(conn, admission_id=req.admission_id, risks=risks)
    _insert_alerts(conn, admission_id=req.admission_id, patient_id=patient_id, bed_id=bed_id, risks=risks)
    _update_active_risks(conn, admission_id=req.admission_id, risks=risks, escalation_level=escalation_level)

    # Convert to API response schema
    now = datetime.now(timezone.utc)
    out_risks: list[RiskImage] = []
    for r in risks:
        out_risks.append(
            RiskImage(
                risk_type=str(r["risk_type"]),
                confidence=cast(Decimal, r["confidence"]),
                severity=cast(RiskSeverity, str(r["severity"])),
                evidence=cast(list[dict[str, Any]], r["evidence"]),
                time_window=str(r["time_window"]),
                recommended_action=str(r["recommended_action"]),
            )
        )

    return RiskSentinelEvaluateResponse(
        admission_id=req.admission_id,
        risks=out_risks,
        escalation_level=cast(str, escalation_level),
        generated_at=now,
    )

