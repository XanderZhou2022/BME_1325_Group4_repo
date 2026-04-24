"""Service logic for Clinical Summary Agent."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

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
    build_problem_items,
    deduce_problems,
    generate_summary_text,
    generate_focus_areas,
)


def _ensure_clinical_summary_table(conn: Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS clinical_summaries (
                summary_id TEXT PRIMARY KEY,
                admission_id TEXT NOT NULL REFERENCES admissions(admission_id),
                patient_id TEXT NOT NULL REFERENCES patients(patient_id),
                bed_id TEXT NOT NULL REFERENCES beds(bed_id),
                generated_at TIMESTAMPTZ NOT NULL,
                summary_type TEXT NOT NULL,
                one_line_status TEXT,
                clinical_summary TEXT,
                active_problem_list JSONB NOT NULL DEFAULT '[]'::jsonb,
                key_events JSONB NOT NULL DEFAULT '[]'::jsonb,
                key_interventions_and_responses JSONB NOT NULL DEFAULT '[]'::jsonb,
                recommended_attention_targets JSONB NOT NULL DEFAULT '[]'::jsonb,
                uncertainties_or_missing_data JSONB NOT NULL DEFAULT '[]'::jsonb,
                urgency_level TEXT,
                source_event_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )


def generate_summary(req: ClinicalSummaryRequest, *, summary_type: str = "current_status_summary") -> ClinicalSummaryResponse:
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
    problem_items = build_problem_items(problems)
    last_24h_key_events = list(req.memory_context.unresolved_problems[:5])
    one_line_status = (
        f"Bed {req.bed_id} has {problems[0].problem.lower()} with {problems[0].urgency} urgency."
        if problems
        else f"Bed {req.bed_id} has no major active risk signal."
    )
    key_interventions = [
        {
            "intervention": ir.intervention_type,
            "response": ir.response_assessment,
            "summary": f"{ir.intervention_type} -> {ir.response_assessment}",
        }
        for ir in req.intervention_responses[:3]
    ]
    uncertainties = []
    if not req.active_risks:
        uncertainties.append("No latest risk_assessments available.")
    if not req.intervention_responses:
        uncertainties.append("No recent intervention response available.")
    urgency_level = "critical" if any(p.urgency == "critical" for p in problems) else ("warning" if any(p.urgency == "warning" for p in problems) else "info")

    problem_str = ", ".join([f"{p.problem} ({p.urgency})" for p in problems]) if problems else "None identified"
    if summary_type == "24h_round_summary":
        clinical_narrative = " ".join(
            [
                f"Patient admitted for {req.memory_context.admission_reason}.",
                f"24h problem overview: {problem_str}.",
                f"Summary: {summary_text}",
                f"Round focus: {', '.join(focus_areas)}.",
            ]
        )
    else:
        clinical_narrative = " ".join(
            [
                f"Patient admitted for {req.memory_context.admission_reason}.",
                f"Current active problems: {problem_str}.",
                f"Current status summary: {summary_text}",
                f"Immediate attention: {', '.join(focus_areas[:2]) if focus_areas else 'continue close monitoring'}.",
            ]
        )

    return ClinicalSummaryResponse(
        patient_id=req.patient_id,
        bed_id=req.bed_id,
        admission_id=req.admission_id,
        generated_at=datetime.now(timezone.utc),
        summary_type=cast(Any, summary_type),
        one_line_status=one_line_status,
        icu_course_context=f"Patient admitted for {req.memory_context.admission_reason}.",
        last_24h_key_events=last_24h_key_events,
        active_problem_list=problem_items,
        key_interventions_and_responses=key_interventions,
        recommended_attention_targets=focus_areas,
        uncertainties_or_missing_data=uncertainties,
        urgency_level=cast(Any, urgency_level),
        notify_agents=["ward_coordinator", "compassion_agent"],
        twenty_four_hour_summary=summary_text,
        problem_list=problems,
        focus_areas_for_today=focus_areas,
        clinical_narrative=clinical_narrative,
    )


def evaluate_clinical_summary(conn: Connection, admission_id: str, summary_type: str = "current_status_summary") -> ClinicalSummaryResponse:
    _ensure_clinical_summary_table(conn)
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
            trend_labels=[str(x) for x in list(bedside_payload.get("trend_labels") or [])],
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
                urgency_level="critical" if str(r["severity"]) == "critical" else ("warning" if str(r["severity"]) in ("warning", "high") else "info"),
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

    summary = generate_summary(req, summary_type=summary_type if summary_type in ("current_status_summary", "24h_round_summary") else "current_status_summary")
    payload = {
        "schema_version": "clinical_summary.v1.1",
        "agent": "clinical_summary",
        "summary_type": summary.summary_type,
        "one_line_status": summary.one_line_status,
        "icu_course_context": summary.icu_course_context,
        "last_24h_key_events": summary.last_24h_key_events,
        "active_problem_list": summary.active_problem_list,
        "key_interventions_and_responses": summary.key_interventions_and_responses,
        "recommended_attention_targets": summary.recommended_attention_targets,
        "uncertainties_or_missing_data": summary.uncertainties_or_missing_data,
        "urgency_level": summary.urgency_level,
        "notify_agents": summary.notify_agents,
        "24h_rounds_summary": summary.twenty_four_hour_summary,
        "problem_list": [p.model_dump(mode="json") for p in summary.problem_list],
        "focus_areas_for_today": summary.focus_areas_for_today,
        "clinical_narrative": summary.clinical_narrative,
    }

    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_events (
                    event_id, admission_id, patient_id, bed_id, producer_agent,
                    event_type, schema_version, produced_at, output_id, payload
                ) VALUES (%s,%s,%s,%s,'clinical_summary','clinical_summary.started','v1',%s,NULL,%s::jsonb)
                """,
                (new_id("aevt"), admission_id, summary.patient_id, summary.bed_id, datetime.now(timezone.utc), Json({"summary_type": summary.summary_type})),
            )
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
            cur.execute(
                """
                INSERT INTO clinical_summaries (
                    summary_id, admission_id, patient_id, bed_id, generated_at, summary_type,
                    one_line_status, clinical_summary, active_problem_list, key_events,
                    key_interventions_and_responses, recommended_attention_targets,
                    uncertainties_or_missing_data, urgency_level, source_event_ids
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s::jsonb)
                """,
                (
                    new_id("csum"),
                    admission_id,
                    summary.patient_id,
                    summary.bed_id,
                    now,
                    summary.summary_type,
                    summary.one_line_status,
                    summary.clinical_narrative,
                    Json(summary.active_problem_list),
                    Json(summary.last_24h_key_events),
                    Json(summary.key_interventions_and_responses),
                    Json(summary.recommended_attention_targets),
                    Json(summary.uncertainties_or_missing_data),
                    summary.urgency_level,
                    Json([]),
                ),
            )
            cur.execute(
                """
                INSERT INTO audit_logs (id, timestamp, actor, actor_id, action_type, target_type, target_id, input, output)
                VALUES (%s, %s, 'agent', 'clinical_summary', 'run_agent', 'admission', %s, %s::jsonb, %s::jsonb)
                """,
                (
                    new_id("log"),
                    now,
                    admission_id,
                    Json({"admission_id": admission_id, "summary_type": summary.summary_type}),
                    Json({"urgency_level": summary.urgency_level, "problem_count": len(summary.problem_list), "output_id": output_id}),
                ),
            )

    return summary
