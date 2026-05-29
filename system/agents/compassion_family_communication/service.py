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
from llm.schemas import FamilyCommunicationDraftOutput

from .schemas import CompassionDraftRequest, CompassionDraftResponse

COMPASSION_REMINDER = [
    "Do not deliver directly to family without clinician approval.",
    "Do not use as prognosis statement.",
    "Do not use as treatment decision.",
]


def _latest_payload(conn: Connection, admission_id: str, agent_name: str) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT payload FROM agent_outputs
            WHERE admission_id = %s AND agent_name = %s
            ORDER BY generated_at DESC
            LIMIT 1
            """,
            (admission_id, agent_name),
        )
        row = cur.fetchone()
    return row["payload"] if row else {}


def evaluate_compassion_draft(conn: Connection, req: CompassionDraftRequest) -> CompassionDraftResponse:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute("SELECT patient_id, bed_id FROM admissions WHERE admission_id = %s", (req.admission_id,))
        adm = cur.fetchone()
    if not adm:
        raise HTTPException(status_code=404, detail="Admission not found")
    patient_id = adm["patient_id"]
    bed_id = adm["bed_id"]
    summary = _latest_payload(conn, req.admission_id, "clinical_summary")
    memory = _latest_payload(conn, req.admission_id, "patient_memory")
    risk = _latest_payload(conn, req.admission_id, "risk_sentinel")

    query_parts = [
        str(summary.get("one_line_status") or ""),
        " ".join(summary.get("watch_items") or []),
        " ".join(memory.get("communication_relevant_context") or []),
        " ".join([str((r or {}).get("risk_type")) for r in risk.get("active_risks", []) if isinstance(r, dict)]),
    ]
    retrieval = retrieve_cards(
        "compassion_family_communication",
        {"patient_id": patient_id, "bed_id": bed_id},
        trigger_signals=query_parts,
        query=" ".join(query_parts),
    )
    cards = retrieval["retrieved_cards"]
    prompt = load_prompt_template("compassion_family_draft_prompt.md")
    input_payload = {
        "agent_name": "compassion_family_communication",
        "prompt_template_name": "compassion_family_draft_prompt.md",
        "admission_id": req.admission_id,
        "patient_id": patient_id,
        "bed_id": bed_id,
        "draft_type": req.draft_type,
        "clinical_summary": summary,
        "patient_memory": memory,
        "risk_sentinel_high_level": {
            "overall_risk_level": risk.get("overall_risk_level"),
            "active_risks": risk.get("active_risks") or [],
        },
        "retrieved_knowledge_cards": cards,
        "global_forbidden_use": [
            "direct_family_delivery_without_clinician_review",
            "prognosis_claim",
            "death_risk_prediction",
            "treatment_decision",
            "diagnosis",
            "false_reassurance",
        ],
    }
    result = generate_structured_output(
        "compassion_family_draft",
        prompt,
        input_payload,
        FamilyCommunicationDraftOutput,
    )
    output = result.output.model_dump(mode="json")
    now = datetime.now(timezone.utc)
    response = CompassionDraftResponse(
        admission_id=req.admission_id,
        patient_id=patient_id,
        bed_id=bed_id,
        draft_type=output["draft_type"],
        clinician_review_version=output["clinician_review_version"],
        family_plain_language_draft=output["family_plain_language_draft"],
        icu_diary_draft=output.get("icu_diary_draft"),
        communication_cautions=output.get("communication_cautions") or [],
        what_not_to_say=output.get("what_not_to_say") or [],
        supporting_card_ids=output.get("supporting_card_ids") or [c["card_id"] for c in cards],
        knowledge_context=cards,
        forbidden_use_reminder=output.get("forbidden_use_reminder") or COMPASSION_REMINDER,
        requires_clinician_approval_before_delivery=True,
        generated_at=now,
        knowledge_used=bool(cards),
        llm_used=result.llm_used,
        fallback_used=result.fallback_used,
        audit_log_id=result.audit_log_id,
        human_review_required=True,
    )
    payload = response.model_dump(mode="json")
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_registry (agent_name, input_event_types, output_event_type, schema_version, enabled)
                VALUES ('compassion_family_communication', '["clinical_summary_ready","patient_memory_ready"]'::jsonb, 'family_communication_draft_ready', 'v1', TRUE)
                ON CONFLICT (agent_name) DO UPDATE SET enabled = TRUE, updated_at = NOW()
                """
            )
            output_id = new_id("out")
            cur.execute(
                """
                INSERT INTO agent_outputs (
                    output_id, admission_id, patient_id, bed_id, agent_name,
                    schema_version, output_type, generated_at, payload
                ) VALUES (%s, %s, %s, %s, 'compassion_family_communication', 'v1', 'family_communication_draft_ready', %s, %s::jsonb)
                """,
                (output_id, req.admission_id, patient_id, bed_id, now, Json(payload)),
            )
            cur.execute(
                """
                INSERT INTO agent_events (
                    event_id, admission_id, patient_id, bed_id, producer_agent,
                    event_type, schema_version, produced_at, output_id, payload
                ) VALUES (%s, %s, %s, %s, 'compassion_family_communication', 'family_communication_draft_ready', 'v1', %s, %s, %s::jsonb)
                """,
                (new_id("aevt"), req.admission_id, patient_id, bed_id, now, output_id, Json(payload)),
            )
            cur.execute(
                """
                INSERT INTO audit_logs (id, timestamp, actor, actor_id, action_type, target_type, target_id, input, output)
                VALUES (%s, %s, 'agent', 'compassion_family_communication', 'run_agent', 'admission', %s, %s::jsonb, %s::jsonb)
                """,
                (
                    new_id("log"),
                    now,
                    req.admission_id,
                    Json({"admission_id": req.admission_id, "draft_type": req.draft_type}),
                    Json({"output_id": output_id, "llm_audit_log_id": result.audit_log_id, "retrieved_card_ids": [c["card_id"] for c in cards]}),
                ),
            )
    return response
