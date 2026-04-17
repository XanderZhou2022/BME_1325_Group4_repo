"""Service logic for Clinical Summary Agent."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.services.ids import new_id

from .schemas import (
    ClinicalSummaryRequest,
    ClinicalSummaryResponse,
    ProblemListItem,
    VitalsSummary,
    InterventionResponse,
    ActiveRisk,
    MemoryContext,
)
from .templates import (
    deduce_problems,
    generate_summary_text,
    generate_focus_areas,
)


def generate_summary(req: ClinicalSummaryRequest) -> ClinicalSummaryResponse:
    problems: list[ProblemListItem] = deduce_problems(
        vitals_summary=req.vitals_summary,
        active_risks=req.active_risks,
        intervention_responses=req.intervention_responses,
    )

    summary_text = generate_summary_text(
        admission_reason=req.memory_context.admission_reason,
        problems=problems,
        interventions=req.intervention_responses,
        unresolved_problems=req.memory_context.unresolved_problems,
    )

    focus_areas = generate_focus_areas(
        problems=problems,
        interventions=req.intervention_responses,
    )

    problem_str = ", ".join([f"{p.problem} ({p.urgency})" for p in problems]) if problems else "None identified"
    clinical_narrative = " ".join(
        [
            f"Patient admitted for {req.memory_context.admission_reason}.",
            f"Current active problems: {problem_str}.",
            f"Summary: {summary_text}",
            f"Focus: {', '.join(focus_areas)}.",
        ]
    )

    return ClinicalSummaryResponse(
        patient_id=req.patient_id,
        bed_id=req.bed_id,
        admission_id=req.admission_id,
        generated_at=datetime.now(timezone.utc),
        twenty_four_hour_summary=summary_text,
        problem_list=problems,
        focus_areas_for_today=focus_areas,
        clinical_narrative=clinical_narrative,
    )


def evaluate_clinical_summary(conn: Connection, admission_id: str) -> ClinicalSummaryResponse:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute("SELECT patient_id, bed_id, admission_reason FROM admissions WHERE admission_id = %s", (admission_id,))
        adm = cur.fetchone()
        if not adm:
            raise HTTPException(status_code=404, detail="Admission not found")

        cur.execute(
            """
            SELECT payload FROM agent_outputs
            WHERE admission_id = %s AND agent_name = 'bedside_monitor'
            ORDER BY generated_at DESC
            LIMIT 1
            """,
            (admission_id,),
        )
        bedside_row = cur.fetchone()

        cur.execute(
            """
            SELECT payload FROM agent_outputs
            WHERE admission_id = %s AND agent_name = 'intervention_tracker'
            ORDER BY generated_at DESC
            LIMIT 1
            """,
            (admission_id,),
        )
        intv_row = cur.fetchone()

        cur.execute(
            """
            SELECT risk_type, confidence, evidence, severity
            FROM risk_assessments
            WHERE admission_id = %s
            ORDER BY timestamp DESC
            LIMIT 5
            """,
            (admission_id,),
        )
        risk_rows = cur.fetchall()

        cur.execute(
            """
            SELECT payload FROM agent_outputs
            WHERE admission_id = %s AND agent_name = 'patient_memory'
            ORDER BY generated_at DESC
            LIMIT 1
            """,
            (admission_id,),
        )
        mem_row = cur.fetchone()

    bedside_payload = bedside_row["payload"] if bedside_row else {}
    intv_payload = intv_row["payload"] if intv_row else {}
    mem_payload = mem_row["payload"] if mem_row else {}

    req = ClinicalSummaryRequest(
        patient_id=adm["patient_id"],
        bed_id=adm["bed_id"],
        admission_id=admission_id,
        vitals_summary=VitalsSummary(
            abnormal_flags=list(bedside_payload.get("abnormal_flags") or []),
            trend_labels=list(bedside_payload.get("trend_labels") or []),
            evidence=list(bedside_payload.get("evidence") or []),
        ),
        intervention_responses=[
            InterventionResponse(
                intervention_id="latest",
                intervention_type=str(intv_payload.get("intervention_type") or "fluid"),
                intervention_time=datetime.now(timezone.utc),
                response_assessment=str(intv_payload.get("response_assessment") or "non_responsive"),
                target_metrics=dict(intv_payload.get("target_metrics") or {}),
                before_after_comparison=dict(intv_payload.get("before_after_comparison") or {}),
            )
        ] if intv_payload else [],
        active_risks=[
            ActiveRisk(
                risk_type=r["risk_type"],
                confidence=float(r["confidence"]),
                evidence=str(r["evidence"]),
                urgency_level="critical" if r["severity"] == "critical" else "warning",
            )
            for r in risk_rows
        ],
        memory_context=MemoryContext(
            admission_reason=str(adm["admission_reason"]),
            major_icu_course=["auto_generated"],
            unresolved_problems=list(mem_payload.get("trend_vectors", {}).keys()) if mem_payload else [],
            key_turning_points=["latest_window"],
        ),
    )

    summary = generate_summary(req)
    payload = {
        "24h_rounds_summary": summary.twenty_four_hour_summary,
        "problem_list": [p.model_dump(mode="json") for p in summary.problem_list],
        "focus_areas_for_today": summary.focus_areas_for_today,
        "clinical_narrative": summary.clinical_narrative,
    }

    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_registry (agent_name, input_event_types, output_event_type, schema_version, enabled)
                VALUES ('clinical_summary', '["patient_memory_ready","risk_assessment_ready"]'::jsonb, 'clinical_summary_ready', 'v1', TRUE)
                ON CONFLICT (agent_name) DO UPDATE SET enabled = TRUE, updated_at = NOW()
                """
            )
            output_id = new_id("out")
            event_id = new_id("aevt")
            now = datetime.now(timezone.utc)
            cur.execute(
                """
                INSERT INTO agent_outputs (
                    output_id, admission_id, patient_id, bed_id, agent_name,
                    schema_version, output_type, generated_at, payload
                ) VALUES (%s,%s,%s,%s,'clinical_summary','v1','clinical_summary_ready',%s,%s::jsonb)
                """,
                (output_id, admission_id, summary.patient_id, summary.bed_id, now, Json(payload)),
            )
            cur.execute(
                """
                INSERT INTO agent_events (
                    event_id, admission_id, patient_id, bed_id, producer_agent,
                    event_type, schema_version, produced_at, output_id, payload
                ) VALUES (%s,%s,%s,%s,'clinical_summary','clinical_summary_ready','v1',%s,%s,%s::jsonb)
                """,
                (event_id, admission_id, summary.patient_id, summary.bed_id, now, output_id, Json(payload)),
            )

    return summary
