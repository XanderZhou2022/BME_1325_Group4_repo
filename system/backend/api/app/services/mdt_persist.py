from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from psycopg import Connection
from psycopg.types.json import Json

from app.config import get_settings
from app.services.ids import new_id


def save_mdt_agent_output(
    conn: Connection,
    *,
    admission_id: str,
    patient_id: str,
    bed_id: str,
    bridge_response: dict[str, Any],
) -> str:
    settings = get_settings()
    output_id = new_id("out")
    now = datetime.now(timezone.utc)
    output_type = str(
        bridge_response.get("mdt_output_type")
        or ("mdt_final_treatment_plan" if bridge_response.get("finalized") else "mdt_required_updates")
    )
    payload = {
        **bridge_response,
        "simi_base_url": settings.simi_mdt_base_url,
        "bridge_schema_version": bridge_response.get("schema_version", "simi_hospital.icu_bridge.v1"),
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_outputs (
                output_id, admission_id, patient_id, bed_id, agent_name,
                schema_version, output_type, generated_at, payload
            ) VALUES (%s, %s, %s, %s, 'mdt_consultation', 'mdt_to_icu.v1', %s, %s, %s::jsonb)
            """,
            (output_id, admission_id, patient_id, bed_id, output_type, now, Json(payload)),
        )
        event_id = new_id("aevt")
        cur.execute(
            """
            INSERT INTO agent_events (
                event_id, admission_id, patient_id, bed_id, producer_agent,
                event_type, schema_version, produced_at, output_id, payload
            ) VALUES (%s, %s, %s, %s, 'mdt_consultation', 'mdt_consultation_ready', 'mdt_to_icu.v1', %s, %s, %s::jsonb)
            """,
            (event_id, admission_id, patient_id, bed_id, now, output_id, Json({"output_id": output_id, "consultation_id": bridge_response.get("consultation_id")})),
        )
    conn.commit()
    return output_id
