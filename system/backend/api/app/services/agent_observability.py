from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from psycopg import Connection
from psycopg.types.json import Json

from app.services.ids import new_id
from app.services.hospital_bus import mirror_agent_event_row


def emit_agent_lifecycle_event(
    conn: Connection,
    *,
    admission_id: str,
    patient_id: str,
    bed_id: str,
    producer_agent: str,
    lifecycle: str,
    payload: dict[str, Any] | None = None,
) -> str:
    event_id = new_id("aevt")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_events (
                event_id, admission_id, patient_id, bed_id, producer_agent,
                event_type, schema_version, produced_at, output_id, payload
            ) VALUES (%s, %s, %s, %s, %s, %s, 'v1', %s, NULL, %s::jsonb)
            """,
            (
                event_id,
                admission_id,
                patient_id,
                bed_id,
                producer_agent,
                f"{producer_agent}.{lifecycle}",
                datetime.now(timezone.utc),
                Json(payload or {}),
            ),
        )
        cur.execute(
            "SELECT encounter_id FROM admissions WHERE admission_id = %s",
            (admission_id,),
        )
        enc_row = cur.fetchone()
    encounter_id = enc_row[0] if enc_row else None
    pl = payload or {}
    mirror_agent_event_row(
        table_event_id=event_id,
        admission_id=admission_id,
        patient_id=patient_id,
        bed_id=bed_id,
        producer_agent=producer_agent,
        internal_event_type=f"{producer_agent}.{lifecycle}",
        payload=pl if isinstance(pl, dict) else {},
        encounter_id=encounter_id,
    )
    return event_id


def write_run_audit(
    conn: Connection,
    *,
    actor: str,
    actor_id: str,
    action_type: str,
    target_type: str,
    target_id: str,
    input_obj: dict[str, Any],
    output_obj: dict[str, Any],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit_logs (id, timestamp, actor, actor_id, action_type, target_type, target_id, input, output)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
            """,
            (
                new_id("log"),
                datetime.now(timezone.utc),
                actor,
                actor_id,
                action_type,
                target_type,
                target_id,
                Json(input_obj),
                Json(output_obj),
            ),
        )
