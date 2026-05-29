from __future__ import annotations

import contextvars
import json
import os
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.services.ids import new_id

_audit_conn: contextvars.ContextVar[Connection | None] = contextvars.ContextVar("icu_audit_conn", default=None)


def bind_audit_connection(conn: Connection | None) -> None:
    """Reuse the worker's DB connection for audit writes (avoids connection storms under parallel demo)."""
    _audit_conn.set(conn)


def _resolve_dsn() -> str:
    dsn = os.getenv("ICU_PG_DSN", "").strip()
    if dsn:
        return dsn
    from app.config import get_settings

    return get_settings().pg_dsn


def _extract_admission_id(record: dict[str, Any]) -> str | None:
    admission_id = record.get("admission_id")
    if admission_id:
        return str(admission_id)
    input_payload = record.get("input_payload")
    if isinstance(input_payload, dict):
        nested = input_payload.get("admission_id")
        if nested:
            return str(nested)
    return None


def write_llm_audit(record: dict[str, Any], conn: Connection | None = None) -> str:
    audit_id = str(record.get("audit_log_id") or new_id("llmaudit"))
    timestamp_raw = record.get("timestamp")
    if isinstance(timestamp_raw, datetime):
        timestamp = timestamp_raw if timestamp_raw.tzinfo else timestamp_raw.replace(tzinfo=timezone.utc)
    elif isinstance(timestamp_raw, str) and timestamp_raw.strip():
        timestamp = datetime.fromisoformat(timestamp_raw.replace("Z", "+00:00"))
    else:
        timestamp = datetime.now(timezone.utc)

    input_payload = record.get("input_payload")
    if not isinstance(input_payload, dict):
        input_payload = {}

    payload = {
        "audit_log_id": audit_id,
        "timestamp": timestamp.isoformat(),
        **record,
    }
    row = {
        "audit_log_id": audit_id,
        "timestamp": timestamp,
        "task_name": str(record.get("task_name") or ""),
        "agent_name": record.get("agent_name"),
        "patient_id": record.get("patient_id"),
        "admission_id": _extract_admission_id(record),
        "prompt_template": record.get("prompt_template"),
        "model": record.get("model"),
        "llm_enabled": bool(record.get("llm_enabled")),
        "schema_valid": record.get("schema_valid"),
        "safety_valid": record.get("safety_valid"),
        "fallback_used": bool(record.get("fallback_used")),
        "error": record.get("error"),
        "retrieved_card_ids": record.get("retrieved_card_ids") or [],
        "input_payload": input_payload,
        "raw_output": record.get("raw_output"),
        "parsed_output": record.get("parsed_output"),
        "record": payload,
    }

    sql = """
        INSERT INTO llm_audit_logs (
            audit_log_id, timestamp, task_name, agent_name, patient_id, admission_id,
            prompt_template, model, llm_enabled, schema_valid, safety_valid, fallback_used,
            error, retrieved_card_ids, input_payload, raw_output, parsed_output, record
        ) VALUES (
            %(audit_log_id)s, %(timestamp)s, %(task_name)s, %(agent_name)s, %(patient_id)s, %(admission_id)s,
            %(prompt_template)s, %(model)s, %(llm_enabled)s, %(schema_valid)s, %(safety_valid)s, %(fallback_used)s,
            %(error)s, %(retrieved_card_ids)s::jsonb, %(input_payload)s::jsonb, %(raw_output)s,
            %(parsed_output)s::jsonb, %(record)s::jsonb
        )
        ON CONFLICT (audit_log_id) DO UPDATE SET
            timestamp = EXCLUDED.timestamp,
            task_name = EXCLUDED.task_name,
            agent_name = EXCLUDED.agent_name,
            patient_id = EXCLUDED.patient_id,
            admission_id = EXCLUDED.admission_id,
            prompt_template = EXCLUDED.prompt_template,
            model = EXCLUDED.model,
            llm_enabled = EXCLUDED.llm_enabled,
            schema_valid = EXCLUDED.schema_valid,
            safety_valid = EXCLUDED.safety_valid,
            fallback_used = EXCLUDED.fallback_used,
            error = EXCLUDED.error,
            retrieved_card_ids = EXCLUDED.retrieved_card_ids,
            input_payload = EXCLUDED.input_payload,
            raw_output = EXCLUDED.raw_output,
            parsed_output = EXCLUDED.parsed_output,
            record = EXCLUDED.record
    """
    params = {
        **row,
        "retrieved_card_ids": Json(row["retrieved_card_ids"]),
        "input_payload": Json(row["input_payload"]),
        "parsed_output": Json(row["parsed_output"]) if row["parsed_output"] is not None else None,
        "record": Json(row["record"]),
    }

    effective_conn = conn or _audit_conn.get()
    if effective_conn is not None:
        with effective_conn.cursor() as cur:
            cur.execute(sql, params)
        return audit_id

    with psycopg.connect(_resolve_dsn(), connect_timeout=10) as own_conn:
        with own_conn.cursor() as cur:
            cur.execute(sql, params)
        own_conn.commit()
    return audit_id


def get_llm_audit(audit_log_id: str, conn: Connection | None = None) -> dict[str, Any] | None:
    sql = "SELECT record FROM llm_audit_logs WHERE audit_log_id = %s"
    if conn is not None:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, (audit_log_id,))
            row = cur.fetchone()
        if not row:
            return None
        record = row.get("record")
        return dict(record) if isinstance(record, dict) else None

    with psycopg.connect(_resolve_dsn(), row_factory=dict_row) as own_conn:
        with own_conn.cursor() as cur:
            cur.execute(sql, (audit_log_id,))
            row = cur.fetchone()
    if not row:
        return None
    record = row.get("record")
    return dict(record) if isinstance(record, dict) else None


def list_llm_audit_logs(
    conn: Connection,
    *,
    admission_id: str | None = None,
    patient_id: str | None = None,
    since: datetime | None = None,
    scenario_tag: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 500))
    conn.row_factory = dict_row
    clauses: list[str] = []
    params: list[Any] = []

    if since is not None:
        clauses.append("l.timestamp >= %s")
        params.append(since)
    if admission_id:
        clauses.append("l.admission_id = %s")
        params.append(admission_id)
    if patient_id:
        clauses.append("l.patient_id = %s")
        params.append(patient_id)
    if scenario_tag:
        clauses.append(
            """
            (
                l.admission_id IN (SELECT admission_id FROM admissions WHERE scenario_tag = %s)
                OR l.patient_id IN (SELECT patient_id FROM admissions WHERE scenario_tag = %s)
            )
            """
        )
        params.extend([scenario_tag, scenario_tag])

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT l.record
            FROM llm_audit_logs l
            {where}
            ORDER BY l.timestamp DESC
            LIMIT %s
            """,
            params,
        )
        rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        record = row.get("record")
        if isinstance(record, dict):
            out.append(dict(record))
    return out


def list_llm_audit_log_ids(
    conn: Connection,
    *,
    admission_id: str | None = None,
    since: datetime | None = None,
    scenario_tag: str | None = None,
    limit: int = 100,
) -> list[str]:
    limit = max(1, min(limit, 500))
    conn.row_factory = dict_row
    clauses: list[str] = []
    params: list[Any] = []

    if since is not None:
        clauses.append("timestamp >= %s")
        params.append(since)
    if admission_id:
        clauses.append("admission_id = %s")
        params.append(admission_id)
    if scenario_tag:
        clauses.append(
            """
            (
                admission_id IN (SELECT admission_id FROM admissions WHERE scenario_tag = %s)
                OR patient_id IN (SELECT patient_id FROM admissions WHERE scenario_tag = %s)
            )
            """
        )
        params.extend([scenario_tag, scenario_tag])

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT audit_log_id
            FROM llm_audit_logs
            {where}
            ORDER BY timestamp ASC
            LIMIT %s
            """,
            params,
        )
        return [str(r["audit_log_id"]) for r in cur.fetchall()]


def import_llm_audit_jsonl(path: str, *, conn: Connection | None = None) -> int:
    """One-time import from legacy logs/llm_audit.jsonl."""
    imported = 0
    own_conn: Connection | None = None
    if conn is None:
        own_conn = psycopg.connect(_resolve_dsn())
        conn = own_conn

    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    continue
                write_llm_audit(record, conn=conn)
                imported += 1
        if own_conn is not None:
            own_conn.commit()
    finally:
        if own_conn is not None:
            own_conn.close()
    return imported
