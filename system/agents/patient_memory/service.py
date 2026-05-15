from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.services.ids import new_id
from knowledge.retriever import retrieve_cards
from llm.client import generate_structured_output
from llm.prompt_loader import load_prompt_template
from llm.schemas import PatientMemoryNarrativeOutput

from .schemas import (
    LongTermMemory,
    MemoryEvaluateRequest,
    MemoryEvaluateResponse,
    MemoryRequest,
    MidTermMemory,
    ShortTermMemory,
    TemporalStateSummary,
    VitalSignEvent,
    LabEvent,
    InterventionEvent,
)
from .memory_manager import calculate_trend_for_metric, calculate_volatility, extract_window_data

MEMORY_REMINDER = [
    "Do not use this memory narrative as a diagnosis.",
    "Do not use this memory narrative as a treatment recommendation.",
    "Do not infer prognosis from this output.",
    "Clinician review is required.",
]


def process_memory(request: MemoryRequest) -> TemporalStateSummary:
    current_time = datetime.now(timezone.utc)
    vital_metrics = ["heart_rate", "mean_arterial_pressure", "respiratory_rate", "temperature", "spo2"]
    current_vitals = {}
    trend_vectors = {}
    volatility_index = {}
    all_completeness = []

    for metric in vital_metrics:
        def extractor(e):
            return getattr(e, metric)

        def time_ext(e):
            return e.timestamp

        values, _times, comp = extract_window_data(
            request.vital_sign_events, current_time, request.window_hours, extractor, time_ext
        )
        all_completeness.append(comp)

        if values:
            current_vitals[metric] = values[-1]
            trend_vectors[metric] = calculate_trend_for_metric(metric, values)
            volatility_index[metric] = calculate_volatility(values)
        else:
            current_vitals[metric] = None

    interventions_sorted = sorted(request.intervention_events, key=lambda x: x.timestamp, reverse=True)
    latest_interventions = interventions_sorted[:3]
    avg_completeness = sum(all_completeness) / len(all_completeness) if all_completeness else 0.0

    return TemporalStateSummary(
        admission_id=request.admission_id,
        window_hours=request.window_hours,
        current_vitals=current_vitals,
        trend_vectors=trend_vectors,
        volatility_index=volatility_index,
        latest_interventions=latest_interventions,
        data_completeness_ratio=avg_completeness,
        snapshot_generated_at=current_time,
    )


def _ensure_memory_tables(conn: Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS patient_memory (
                memory_id TEXT PRIMARY KEY,
                admission_id TEXT NOT NULL REFERENCES admissions(admission_id),
                patient_id TEXT NOT NULL REFERENCES patients(patient_id),
                bed_id TEXT NOT NULL REFERENCES beds(bed_id),
                updated_at TIMESTAMPTZ NOT NULL,
                short_term_summary TEXT,
                mid_term_summary TEXT,
                long_term_summary TEXT,
                active_problems JSONB NOT NULL DEFAULT '[]'::jsonb,
                unresolved_issues JSONB NOT NULL DEFAULT '[]'::jsonb,
                key_events JSONB NOT NULL DEFAULT '[]'::jsonb,
                response_patterns JSONB NOT NULL DEFAULT '[]'::jsonb,
                source_event_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS patient_memory_events (
                memory_event_id TEXT PRIMARY KEY,
                admission_id TEXT NOT NULL REFERENCES admissions(admission_id),
                patient_id TEXT NOT NULL REFERENCES patients(patient_id),
                bed_id TEXT NOT NULL REFERENCES beds(bed_id),
                timestamp TIMESTAMPTZ NOT NULL,
                source_agent TEXT,
                event_type TEXT,
                event_summary TEXT,
                importance_level TEXT,
                related_intervention_id TEXT,
                related_vital_event_id TEXT,
                evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )


def _important_from_agent_outputs(conn: Connection, admission_id: str) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT output_id, agent_name, generated_at, payload
            FROM agent_outputs
            WHERE admission_id = %s
              AND agent_name IN ('bedside_monitor', 'intervention_tracker')
            ORDER BY generated_at DESC
            LIMIT 50
            """,
            (admission_id,),
        )
        rows = cur.fetchall()
    important: list[dict[str, Any]] = []
    for row in rows:
        payload = row["payload"] or {}
        agent = str(row["agent_name"])
        if agent == "bedside_monitor":
            urgency = str(payload.get("urgency_level") or "info")
            if urgency in ("warning", "critical"):
                important.append(
                    {
                        "source_event_id": row["output_id"],
                        "source_agent": "bedside_monitor",
                        "event_type": "vital_summary",
                        "event_summary": str(payload.get("current_status_summary") or "bedside abnormal"),
                        "importance_level": urgency,
                        "evidence": payload,
                    }
                )
        if agent == "intervention_tracker":
            label = str(payload.get("response_label") or payload.get("response_assessment") or "")
            if label in ("non_responsive", "deteriorating_despite_intervention", "not_enough_data", "pending_insufficient_data"):
                important.append(
                    {
                        "source_event_id": row["output_id"],
                        "source_agent": "intervention_tracker",
                        "event_type": "intervention_response",
                        "event_summary": str(payload.get("response_summary") or f"intervention {label}"),
                        "importance_level": "warning" if label != "deteriorating_despite_intervention" else "critical",
                        "evidence": payload,
                    }
                )
    return important


def _important_from_labs(labs: list[LabEvent]) -> list[dict[str, Any]]:
    important: list[dict[str, Any]] = []
    for lab in labs[:50]:
        if str(lab.abnormal_flag or "").lower() in ("high", "low") and str(lab.lab_type).lower() in ("lactate", "creatinine", "abg", "wbc"):
            important.append(
                {
                    "source_event_id": lab.id or "",
                    "source_agent": "lab_events",
                    "event_type": "lab_update",
                    "event_summary": f"{lab.lab_type}={lab.value} {lab.unit} ({lab.abnormal_flag})",
                    "importance_level": "warning",
                    "evidence": lab.model_dump(mode="json"),
                }
            )
    return important


def _build_three_layer_memory(
    *,
    admission_reason: str,
    important_events: list[dict[str, Any]],
    summary: TemporalStateSummary,
) -> tuple[ShortTermMemory, MidTermMemory, LongTermMemory, list[str], list[str], list[str], list[str]]:
    key_events = [str(e.get("event_summary") or "") for e in important_events[:8] if e.get("event_summary")]
    unstable_features: list[str] = []
    for e in important_events:
        ev = str(e.get("event_summary") or "").lower()
        if "hypotension" in ev:
            unstable_features.append("persistent_hypotension")
        if "lactate" in ev:
            unstable_features.append("rising_lactate")
        if "deteriorating" in ev:
            unstable_features.append("treatment_non_response")
    unstable_features = list(dict.fromkeys(unstable_features))

    active_problems = list(dict.fromkeys(unstable_features or list(summary.trend_vectors.keys())[:3]))
    unresolved = list(dict.fromkeys(active_problems[:]))
    response_patterns = []
    if any("intervention" in str(e.get("source_agent")) for e in important_events):
        response_patterns.append("limited_response_to_recent_interventions")

    short = ShortTermMemory(
        time_window="last_6h",
        key_events=key_events[:5],
        current_unstable_features=active_problems[:5],
    )
    mid = MidTermMemory(
        time_window="last_24h",
        major_changes=key_events[:5] if key_events else ["No major deterioration signal in last 24h."],
        unresolved_problems=unresolved[:5],
    )
    long_summary = (
        f"Patient admitted for {admission_reason}. "
        f"Recent ICU course highlights: {('; '.join(key_events[:3]) if key_events else 'no high-importance events captured')}."
    )
    long = LongTermMemory(
        icu_course_summary=long_summary,
        baseline_context=[f"admitted_for_{admission_reason.lower().replace(' ', '_')}"] if admission_reason else [],
        known_response_patterns=response_patterns,
    )
    return short, mid, long, active_problems, unresolved, key_events, response_patterns


def _enrich_memory_narrative(
    *,
    patient_id: str,
    bed_id: str,
    important_events: list[dict[str, Any]],
    active_problems: list[str],
    unresolved: list[str],
    response_patterns: list[str],
    long_summary: str,
    time_window: str,
    llm_enabled: bool | None = None,
) -> dict[str, Any]:
    query_parts = active_problems + unresolved + [str(e.get("event_summary") or "") for e in important_events[:5]]
    retrieval = retrieve_cards(
        "patient_memory",
        {"patient_id": patient_id, "bed_id": bed_id},
        trigger_signals=query_parts,
        query=" ".join(query_parts),
    )
    cards = retrieval["retrieved_cards"]
    prompt = load_prompt_template("patient_memory_narrative_prompt.md")
    input_payload = {
        "agent_name": "patient_memory",
        "prompt_template_name": "patient_memory_narrative_prompt.md",
        "patient_id": patient_id,
        "time_window": time_window,
        "recent_events": important_events[:20],
        "previous_memory": long_summary,
        "active_problems": active_problems,
        "unresolved_issues": unresolved,
        "response_patterns": response_patterns,
        "retrieved_knowledge_cards": cards,
        "global_forbidden_use": ["diagnosis", "treatment_recommendation", "prognosis_claim", "automatic_medical_decision"],
    }
    result = generate_structured_output(
        "patient_memory_narrative",
        prompt,
        input_payload,
        PatientMemoryNarrativeOutput,
        llm_enabled=llm_enabled,
    )
    output = result.output.model_dump(mode="json")
    return {
        "short_term_narrative": output["short_term_narrative"],
        "key_events": output.get("key_events") or [str(e.get("event_summary") or "") for e in important_events[:5]],
        "unresolved_issues": output.get("unresolved_issues") or unresolved,
        "intervention_response_memory": output.get("intervention_response_memory") or response_patterns,
        "communication_relevant_context": output.get("communication_relevant_context") or [],
        "knowledge_context": cards,
        "forbidden_use_reminder": output.get("forbidden_use_reminder") or MEMORY_REMINDER,
        "knowledge_used": bool(cards),
        "llm_used": result.llm_used,
        "fallback_used": result.fallback_used,
        "audit_log_id": result.audit_log_id,
        "human_review_required": True,
    }


def evaluate_memory(conn: Connection, req: MemoryEvaluateRequest) -> MemoryEvaluateResponse:
    _ensure_memory_tables(conn)
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute("SELECT patient_id, bed_id, admission_reason FROM admissions WHERE admission_id = %s", (req.admission_id,))
        admission = cur.fetchone()
        if not admission:
            raise HTTPException(status_code=404, detail="Admission not found")

        cur.execute(
            """
            SELECT id, admission_id, timestamp, heart_rate, mean_arterial_pressure, systolic_bp, diastolic_bp,
                   respiratory_rate, temperature, spo2, fio2, pao2, aado2, ph, gcs
            FROM vital_sign_events
            WHERE admission_id = %s
            ORDER BY timestamp DESC
            LIMIT 500
            """,
            (req.admission_id,),
        )
        vitals_rows = cur.fetchall()

        cur.execute(
            """
            SELECT id, admission_id, timestamp, lab_type, value, unit, abnormal_flag
            FROM lab_events
            WHERE admission_id = %s
            ORDER BY timestamp DESC
            LIMIT 300
            """,
            (req.admission_id,),
        )
        lab_rows = cur.fetchall()

        cur.execute(
            """
            SELECT id, admission_id, timestamp, intervention_type, description, dosage, unit
            FROM intervention_events
            WHERE admission_id = %s
            ORDER BY timestamp DESC
            LIMIT 200
            """,
            (req.admission_id,),
        )
        intervention_rows = cur.fetchall()

    mem_req = MemoryRequest(
        admission_id=req.admission_id,
        window_hours=req.mid_window_hours,
        vital_sign_events=[VitalSignEvent(**r) for r in vitals_rows],
        lab_events=[LabEvent(**r) for r in lab_rows],
        intervention_events=[InterventionEvent(**r) for r in intervention_rows],
    )
    summary = process_memory(mem_req)
    now = datetime.now(timezone.utc)
    important_events = _important_from_agent_outputs(conn, req.admission_id) + _important_from_labs(mem_req.lab_events)
    short, mid, long, active_problems, unresolved, key_events, response_patterns = _build_three_layer_memory(
        admission_reason=str(admission.get("admission_reason") or "unknown_reason"),
        important_events=important_events,
        summary=summary,
    )
    status = "ok" if important_events else "degraded"
    narrative = _enrich_memory_narrative(
        patient_id=admission["patient_id"],
        bed_id=admission["bed_id"],
        important_events=important_events,
        active_problems=active_problems,
        unresolved=unresolved,
        response_patterns=response_patterns,
        long_summary=long.icu_course_summary,
        time_window=f"last_{req.window_hours}h",
    )

    payload = {
        "schema_version": "patient_memory.v1.1",
        "agent": "patient_memory",
        "status": status,
        "admission_id": req.admission_id,
        "patient_id": admission["patient_id"],
        "bed_id": admission["bed_id"],
        "short_term_summary": narrative["short_term_narrative"] or (" ".join(short.key_events) if short.key_events else "No high-importance events in last 6h."),
        "mid_term_summary": " ".join(mid.major_changes) if mid.major_changes else "No major trajectory change in last 24h.",
        "long_term_summary": long.icu_course_summary,
        "active_problems": active_problems,
        "unresolved_issues": unresolved,
        "short_term_memory": short.model_dump(mode="json"),
        "mid_term_memory": mid.model_dump(mode="json"),
        "long_term_memory": long.model_dump(mode="json"),
        "key_events": key_events,
        "response_patterns": response_patterns,
        "source_event_ids": [str(e.get("source_event_id") or "") for e in important_events if e.get("source_event_id")],
        "memory_context_for_risk": {
            "current_main_problem": active_problems[0] if active_problems else "no_dominant_problem",
            "recent_trajectory": "worsening" if important_events else "stable",
            "known_response_pattern": response_patterns[0] if response_patterns else "unknown",
            "unresolved_issues": unresolved,
        },
        "round_memory_for_summary": {
            "icu_course_summary": long.icu_course_summary,
            "last_24h_key_events": mid.major_changes,
            "active_problem_list": active_problems,
        },
        "window_hours": summary.window_hours,
        "current_vitals": summary.current_vitals,
        "trend_vectors": summary.trend_vectors,
        "volatility_index": summary.volatility_index,
        "latest_interventions": [i.model_dump(mode="json") for i in summary.latest_interventions],
        "data_completeness_ratio": summary.data_completeness_ratio,
        "snapshot_generated_at": summary.snapshot_generated_at.isoformat(),
        **narrative,
    }

    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_events (
                    event_id, admission_id, patient_id, bed_id, producer_agent,
                    event_type, schema_version, produced_at, output_id, payload
                ) VALUES (%s, %s, %s, %s, 'patient_memory', 'patient_memory.started', 'v1', %s, NULL, %s::jsonb)
                """,
                (new_id("aevt"), req.admission_id, admission["patient_id"], admission["bed_id"], now, Json({"window_hours": req.window_hours})),
            )
            cur.execute(
                """
                INSERT INTO agent_registry (agent_name, input_event_types, output_event_type, schema_version, enabled)
                VALUES ('patient_memory', '["vital_sign","lab","intervention"]'::jsonb, 'patient_memory_ready', 'v1', TRUE)
                ON CONFLICT (agent_name) DO UPDATE SET enabled = TRUE, updated_at = NOW()
                """
            )
            output_id = new_id("out")
            event_id = new_id("aevt")
            cur.execute(
                """
                INSERT INTO agent_outputs (
                    output_id, admission_id, patient_id, bed_id, agent_name,
                    schema_version, output_type, generated_at, payload
                ) VALUES (%s, %s, %s, %s, 'patient_memory', 'v1', 'patient_memory_ready', %s, %s::jsonb)
                """,
                (output_id, req.admission_id, admission["patient_id"], admission["bed_id"], now, Json(payload)),
            )
            cur.execute(
                """
                INSERT INTO agent_events (
                    event_id, admission_id, patient_id, bed_id, producer_agent,
                    event_type, schema_version, produced_at, output_id, payload
                ) VALUES (%s, %s, %s, %s, 'patient_memory', 'patient_memory_ready', 'v1', %s, %s, %s::jsonb)
                """,
                (event_id, req.admission_id, admission["patient_id"], admission["bed_id"], now, output_id, Json(payload)),
            )
            cur.execute(
                """
                INSERT INTO patient_memory (
                    memory_id, admission_id, patient_id, bed_id, updated_at,
                    short_term_summary, mid_term_summary, long_term_summary,
                    active_problems, unresolved_issues, key_events, response_patterns, source_event_ids
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb)
                """,
                (
                    new_id("mem"),
                    req.admission_id,
                    admission["patient_id"],
                    admission["bed_id"],
                    now,
                    payload["short_term_summary"],
                    payload["mid_term_summary"],
                    payload["long_term_summary"],
                    Json(active_problems),
                    Json(unresolved),
                    Json(key_events),
                    Json(response_patterns),
                    Json(payload["source_event_ids"]),
                ),
            )
            for item in important_events[:20]:
                cur.execute(
                    """
                    INSERT INTO patient_memory_events (
                        memory_event_id, admission_id, patient_id, bed_id, timestamp,
                        source_agent, event_type, event_summary, importance_level,
                        related_intervention_id, related_vital_event_id, evidence
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        new_id("mevt"),
                        req.admission_id,
                        admission["patient_id"],
                        admission["bed_id"],
                        now,
                        item.get("source_agent"),
                        item.get("event_type"),
                        item.get("event_summary"),
                        item.get("importance_level"),
                        None,
                        None,
                        Json(item.get("evidence") or {}),
                    ),
                )
            cur.execute(
                """
                INSERT INTO audit_logs (id, timestamp, actor, actor_id, action_type, target_type, target_id, input, output)
                VALUES (%s, %s, 'agent', 'patient_memory', 'run_agent', 'admission', %s, %s::jsonb, %s::jsonb)
                """,
                (
                    new_id("log"),
                    now,
                    req.admission_id,
                    Json({"admission_id": req.admission_id, "window_hours": req.window_hours, "short_window_hours": req.short_window_hours, "mid_window_hours": req.mid_window_hours}),
                    Json({
                        "status": status,
                        "important_event_count": len(important_events),
                        "active_problems": active_problems,
                        "retrieved_card_ids": [c["card_id"] for c in narrative["knowledge_context"]],
                        "llm_audit_log_id": narrative["audit_log_id"],
                    }),
                ),
            )

    return MemoryEvaluateResponse(
        status=status,
        patient_id=admission["patient_id"],
        bed_id=admission["bed_id"],
        admission_id=req.admission_id,
        window_hours=summary.window_hours,
        short_term_summary=payload["short_term_summary"],
        mid_term_summary=payload["mid_term_summary"],
        long_term_summary=payload["long_term_summary"],
        active_problems=active_problems,
        unresolved_issues=unresolved,
        short_term_memory=short,
        mid_term_memory=mid,
        long_term_memory=long,
        current_vitals=summary.current_vitals,
        trend_vectors=summary.trend_vectors,
        volatility_index=summary.volatility_index,
        latest_interventions=summary.latest_interventions,
        data_completeness_ratio=summary.data_completeness_ratio,
        source_event_ids=payload["source_event_ids"],
        key_events=key_events,
        response_patterns=response_patterns,
        memory_context_for_risk=payload["memory_context_for_risk"],
        round_memory_for_summary=payload["round_memory_for_summary"],
        snapshot_generated_at=summary.snapshot_generated_at,
        generated_at=now,
        short_term_narrative=narrative["short_term_narrative"],
        intervention_response_memory=narrative["intervention_response_memory"],
        communication_relevant_context=narrative["communication_relevant_context"],
        knowledge_context=narrative["knowledge_context"],
        forbidden_use_reminder=narrative["forbidden_use_reminder"],
        knowledge_used=narrative["knowledge_used"],
        llm_used=narrative["llm_used"],
        fallback_used=narrative["fallback_used"],
        audit_log_id=narrative["audit_log_id"],
        human_review_required=True,
    )
