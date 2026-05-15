from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, cast

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.orchestrator.event_dispatcher import dispatch_event_chain
from app.services.event_pipeline import write_intervention, write_lab, write_vital_sign
from app.services.ids import new_encounter_id, new_id
from app.schemas import InterventionEventCreate, LabEventCreate, VitalSignEventCreate

from .schemas import DemoDbEffects, DemoHospitalState, DemoNextResponse, DemoRiskChange, DemoTimelineItem

SIM_TAG = "demo_auto"
SIM_STEP_MINUTES = 5


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def _ensure_demo_tables(conn: Connection) -> None:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS demo_auto_state (
                    id SMALLINT PRIMARY KEY DEFAULT 1,
                    sim_time TIMESTAMPTZ NOT NULL,
                    step_index INT NOT NULL DEFAULT 0,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS demo_auto_timeline (
                    id TEXT PRIMARY KEY,
                    step_index INT NOT NULL,
                    sim_time TIMESTAMPTZ NOT NULL,
                    event_type TEXT NOT NULL,
                    admission_id TEXT,
                    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                    result JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _get_or_create_state(conn: Connection) -> tuple[datetime, int]:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute("SELECT sim_time, step_index FROM demo_auto_state WHERE id = 1")
        row = cur.fetchone()
        if row:
            return cast(datetime, row["sim_time"]), int(row["step_index"])
    return _now_utc(), 0


def _set_state(conn: Connection, sim_time: datetime, step_index: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO demo_auto_state (id, sim_time, step_index, updated_at)
            VALUES (1, %s, %s, NOW())
            ON CONFLICT (id) DO UPDATE SET sim_time = EXCLUDED.sim_time, step_index = EXCLUDED.step_index, updated_at = NOW()
            """,
            (sim_time, step_index),
        )


def _counts(conn: Connection, admission_id: str | None = None) -> dict[str, int]:
    conn.row_factory = dict_row
    where = " WHERE admission_id = %s " if admission_id else ""
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for table, key in [
            ("agent_outputs", "agent_outputs"),
            ("agent_events", "agent_events"),
            ("alerts", "alerts"),
            ("risk_assessments", "risks"),
        ]:
            if admission_id:
                cur.execute(f"SELECT COUNT(*) AS n FROM {table}{where}", (admission_id,))
            else:
                cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
            counts[key] = int(cur.fetchone()["n"])
    return counts


def _risk_snapshot(conn: Connection, admission_id: str | None) -> dict[str, Any]:
    if not admission_id:
        return {}
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT active_risks, care_phase, updated_at
            FROM patient_state_current
            WHERE admission_id = %s
            """,
            (admission_id,),
        )
        state = cur.fetchone()
        cur.execute(
            """
            SELECT id, timestamp, risk_type, severity, confidence, evidence, recommended_action
            FROM risk_assessments
            WHERE admission_id = %s
            ORDER BY timestamp DESC
            LIMIT 10
            """,
            (admission_id,),
        )
        risks = [_json_safe(dict(r)) for r in cur.fetchall()]
    active_risks = _json_safe(state["active_risks"]) if state else []
    severity_rank = {"low": 0, "warning": 1, "critical": 2}
    highest = "none"
    for item in active_risks or []:
        severity = str(item.get("severity") or "low")
        if highest == "none" or severity_rank.get(severity, 0) > severity_rank.get(highest, 0):
            highest = severity
    return {
        "admission_id": admission_id,
        "care_phase": state["care_phase"] if state else None,
        "active_risks": active_risks or [],
        "highest_severity": highest,
        "recent_risk_assessments": risks,
        "updated_at": _json_safe(state["updated_at"]) if state else None,
    }


def _risk_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return (
        before.get("care_phase") != after.get("care_phase")
        or before.get("highest_severity") != after.get("highest_severity")
        or before.get("active_risks") != after.get("active_risks")
        or len(before.get("recent_risk_assessments") or []) != len(after.get("recent_risk_assessments") or [])
    )


def _card_summary(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "card_id": card.get("card_id"),
        "title": card.get("title"),
        "domain": card.get("domain"),
        "card_type": card.get("card_type"),
        "allowed_use": card.get("allowed_use"),
        "human_review_required": card.get("human_review_required", True),
    }


def _knowledge_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    cards: list[dict[str, Any]] = []
    for key in ("knowledge_background", "knowledge_context", "medication_safety_context"):
        value = payload.get(key)
        if isinstance(value, list):
            cards.extend([c for c in value if isinstance(c, dict)])
    retrieval = payload.get("knowledge_retrieval")
    if isinstance(retrieval, dict):
        retrieved_cards = retrieval.get("retrieved_cards")
        if isinstance(retrieved_cards, list):
            cards.extend([c for c in retrieved_cards if isinstance(c, dict)])
    by_id: dict[str, dict[str, Any]] = {}
    for card in cards:
        card_id = str(card.get("card_id") or "")
        if card_id:
            by_id[card_id] = _card_summary(card)
    return {
        "used": bool(by_id) or bool(payload.get("knowledge_used")),
        "retrieved_card_ids": list(by_id.keys()),
        "retrieved_cards": list(by_id.values()),
        "background_count": len(by_id),
    }


def _agent_judgment_from_payload(agent_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    fields_by_agent = {
        "bedside_monitor": ["urgency_level", "current_status_summary", "abnormal_flags", "trend_labels", "next_action_hint", "signal_explanation"],
        "intervention_tracker": ["response_assessment", "response_label", "response_summary", "concern_flags", "urgency_level", "response_explanation", "escalation_hint"],
        "patient_memory": ["status", "short_term_summary", "active_problems", "unresolved_issues", "key_events", "memory_context_for_risk", "short_term_narrative"],
        "risk_sentinel": ["overall_risk_level", "active_risks", "new_or_worsening_flags", "recommended_next_attention", "overall_review_reminder"],
        "clinical_summary": ["urgency_level", "one_line_status", "problem_list", "active_problem_list", "watch_items", "review_reminders"],
        "ward_coordinator": ["ward_load_indicator", "priority_queue", "global_watch_items", "review_reminders", "rationale"],
        "compassion_family_communication": ["communication_cautions", "what_not_to_say", "requires_clinician_approval_before_delivery"],
    }
    picked: dict[str, Any] = {}
    for key in fields_by_agent.get(agent_name, []):
        if key in payload:
            picked[key] = payload[key]
    return _json_safe(picked)


def _llm_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "llm_used": bool(payload.get("llm_used")),
        "fallback_used": bool(payload.get("fallback_used")),
        "audit_log_id": payload.get("audit_log_id"),
        "generated_text_fields": {
            key: payload[key]
            for key in (
                "llm_explanation",
                "short_term_narrative",
                "family_plain_language_draft",
                "icu_diary_draft",
                "rationale",
            )
            if key in payload
        },
    }


def _fetch_agent_workflow_trace(
    conn: Connection,
    *,
    admission_id: str | None,
    since_started_at: datetime,
    include_ward_anchor: bool = True,
) -> list[dict[str, Any]]:
    if not admission_id:
        return []
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT output_id, admission_id, patient_id, bed_id, agent_name, output_type, generated_at, payload
            FROM agent_outputs
            WHERE generated_at >= %s
              AND (
                    admission_id = %s
                    OR (%s AND agent_name = 'ward_coordinator')
                  )
            ORDER BY generated_at ASC, agent_name ASC
            """,
            (since_started_at, admission_id, include_ward_anchor),
        )
        rows = [dict(r) for r in cur.fetchall()]
    trace: list[dict[str, Any]] = []
    for row in rows:
        payload = cast(dict[str, Any], row.get("payload") or {})
        trace.append(
            {
                "agent_name": row["agent_name"],
                "output_id": row["output_id"],
                "output_type": row["output_type"],
                "generated_at": _json_safe(row["generated_at"]),
                "received_context": {
                    "admission_id": row["admission_id"],
                    "patient_id": row["patient_id"],
                    "bed_id": row["bed_id"],
                },
                "knowledge": _knowledge_from_payload(payload),
                "judgment": _agent_judgment_from_payload(str(row["agent_name"]), payload),
                "llm": _llm_from_payload(payload),
                "human_review_required": bool(payload.get("human_review_required", True)),
                "forbidden_use_reminder": payload.get("forbidden_use_reminder") or payload.get("forbidden_use"),
            }
        )
    return trace


def _fetch_audit_log_ids(conn: Connection, *, admission_id: str | None, since_started_at: datetime) -> list[str]:
    if not admission_id:
        return []
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM audit_logs
            WHERE timestamp >= %s
              AND (
                    target_id = %s
                    OR output ->> 'llm_audit_log_id' IS NOT NULL
                    OR actor_id IN ('event_dispatcher', 'bedside_monitor', 'intervention_tracker', 'patient_memory', 'risk_sentinel', 'clinical_summary', 'ward_coordinator', 'compassion_family_communication')
                  )
            ORDER BY timestamp ASC
            LIMIT 100
            """,
            (since_started_at, admission_id),
        )
        return [str(r["id"]) for r in cur.fetchall()]


def _fetch_demo_triggered_agent_rows(
    conn: Connection, *, since_started_at: datetime, scenario_tag: str, limit: int = 400
) -> list[dict[str, Any]]:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT admission_id, patient_id, bed_id, producer_agent, event_type, produced_at, payload
            FROM agent_events
            WHERE produced_at >= %s
              AND admission_id IN (
                  SELECT admission_id FROM admissions WHERE scenario_tag = %s
              )
            ORDER BY produced_at DESC
            LIMIT %s
            """,
            (since_started_at, scenario_tag, limit),
        )
        return [_json_safe(dict(r)) for r in cur.fetchall()]


def _fetch_agent_workflow_trace_demo_batch(
    conn: Connection, *, since_started_at: datetime, scenario_tag: str
) -> list[dict[str, Any]]:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT output_id, admission_id, patient_id, bed_id, agent_name, output_type, generated_at, payload
            FROM agent_outputs
            WHERE generated_at >= %s
              AND (
                    admission_id IN (SELECT admission_id FROM admissions WHERE scenario_tag = %s)
                    OR agent_name = 'ward_coordinator'
                  )
            ORDER BY generated_at ASC, agent_name ASC
            """,
            (since_started_at, scenario_tag),
        )
        rows = [dict(r) for r in cur.fetchall()]
    trace: list[dict[str, Any]] = []
    for row in rows:
        payload = cast(dict[str, Any], row.get("payload") or {})
        trace.append(
            {
                "agent_name": row["agent_name"],
                "output_id": row["output_id"],
                "output_type": row["output_type"],
                "generated_at": _json_safe(row["generated_at"]),
                "received_context": {
                    "admission_id": row["admission_id"],
                    "patient_id": row["patient_id"],
                    "bed_id": row["bed_id"],
                },
                "knowledge": _knowledge_from_payload(payload),
                "judgment": _agent_judgment_from_payload(str(row["agent_name"]), payload),
                "llm": _llm_from_payload(payload),
                "human_review_required": bool(payload.get("human_review_required", True)),
                "forbidden_use_reminder": payload.get("forbidden_use_reminder") or payload.get("forbidden_use"),
            }
        )
    return trace


def _fetch_audit_log_ids_demo_batch(conn: Connection, *, since_started_at: datetime, scenario_tag: str, limit: int = 250) -> list[str]:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM audit_logs
            WHERE timestamp >= %s
              AND (
                    target_id IN (SELECT admission_id FROM admissions WHERE scenario_tag = %s)
                    OR output ->> 'llm_audit_log_id' IS NOT NULL
                    OR actor_id IN ('event_dispatcher', 'bedside_monitor', 'intervention_tracker', 'patient_memory', 'risk_sentinel', 'clinical_summary', 'ward_coordinator', 'compassion_family_communication')
                  )
            ORDER BY timestamp ASC
            LIMIT %s
            """,
            (since_started_at, scenario_tag, limit),
        )
        return [str(r["id"]) for r in cur.fetchall()]


def _active_admissions(conn: Connection) -> list[dict[str, Any]]:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT admission_id, patient_id, bed_id, severity_on_admission, admit_time
            FROM admissions
            WHERE status = 'active' AND scenario_tag = %s
            ORDER BY admit_time DESC
            """,
            (SIM_TAG,),
        )
        return [dict(r) for r in cur.fetchall()]


def _available_demo_bed(conn: Connection) -> str | None:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT bed_id FROM beds
            WHERE bed_id LIKE 'demo_b_%%' AND status = 'empty'
            ORDER BY bed_id
            LIMIT 1
            """,
        )
        row = cur.fetchone()
    return str(row["bed_id"]) if row else None


def _create_patient_bed_admission(
    conn: Connection,
    sim_time: datetime,
    step_index: int,
    *,
    sub_tag: str = "",
    bed_id: str | None = None,
) -> dict[str, Any]:
    stem = f"{step_index:05d}{sub_tag}" if sub_tag else f"{step_index:05d}"
    pid = f"demo_p_{stem}"
    aid = f"demo_adm_{stem}"
    bid = bed_id or f"demo_b_{((step_index - 1) % 20) + 1:02d}"
    sev = random.choice(["stable", "unstable", "critical"])
    encounter_id = new_encounter_id(sim_time)
    care_phase = "critical" if sev == "critical" else "stable"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO patients (patient_id, patient_code, name, gender, age, baseline_profile)
            VALUES (%s, %s, %s, %s, %s, '{}'::jsonb)
            ON CONFLICT (patient_id) DO NOTHING
            """,
            (pid, f"DP{stem}", f"Demo Patient {stem}", random.choice(["male", "female"]), random.randint(22, 88)),
        )
        cur.execute(
            """
            INSERT INTO beds (bed_id, bed_code, room_code, bed_type, status, notes)
            VALUES (%s, %s, 'DEMO', 'icu', 'empty', 'auto demo')
            ON CONFLICT (bed_id) DO NOTHING
            """,
            (bid, bid.upper()),
        )
        cur.execute("UPDATE beds SET status = 'occupied', updated_at = NOW() WHERE bed_id = %s", (bid,))
        cur.execute(
            """
            INSERT INTO admissions (
                admission_id, encounter_id, patient_id, bed_id, admission_code, admit_time, discharge_time,
                status, encounter_status, primary_diagnosis, admission_reason, severity_on_admission,
                attending_team, scenario_tag
            ) VALUES (%s, %s, %s, %s, %s, %s, NULL, 'active', 'ADMITTED', %s, %s, %s, 'DEMO_TEAM', %s)
            """,
            (
                aid,
                encounter_id,
                pid,
                bid,
                f"DEMO-{stem}",
                sim_time,
                random.choice(["sepsis", "respiratory_failure", "post_op"]),
                random.choice(["shock_workup", "hypoxemia", "post-op monitoring"]),
                sev,
                SIM_TAG,
            ),
        )
        cur.execute(
            """
            INSERT INTO patient_state_current (
                admission_id, patient_id, bed_id, current_vitals, active_problems, active_risks,
                latest_interventions, care_phase
            ) VALUES (%s, %s, %s, '{}'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, %s)
            ON CONFLICT (admission_id) DO NOTHING
            """,
            (aid, pid, bid, care_phase),
        )
    return {"admission_id": aid, "encounter_id": encounter_id, "patient_id": pid, "bed_id": bid, "severity": sev}


def _discharge_random(conn: Connection, admission: dict[str, Any], sim_time: datetime) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE admissions
            SET status = 'discharged',
                discharge_time = %s,
                encounter_status = 'DISCHARGED',
                updated_at = NOW()
            WHERE admission_id = %s
            """,
            (sim_time, admission["admission_id"]),
        )
        cur.execute("UPDATE beds SET status = 'empty', updated_at = NOW() WHERE bed_id = %s", (admission["bed_id"],))
    return {"admission_id": admission["admission_id"], "status": "discharged"}


def _write_random_event(conn: Connection, admission: dict[str, Any], sim_time: datetime, event_type: str) -> tuple[dict[str, Any], dict[str, Any]]:
    admission_id = str(admission["admission_id"])
    if event_type == "vital_sign":
        payload = {
            "timestamp": sim_time,
            "source": "monitor",
            "priority": random.choice(["normal", "high"]),
            "heart_rate": random.randint(70, 135),
            "mean_arterial_pressure": Decimal(str(random.randint(52, 92))),
            "respiratory_rate": random.randint(14, 34),
            "temperature": Decimal(str(round(random.uniform(36.0, 39.3), 1))),
            "spo2": Decimal(str(random.randint(86, 99))),
            "gcs": random.randint(9, 15),
        }
        body = VitalSignEventCreate(**payload)
        out = write_vital_sign(conn, admission_id, body)
        out["dispatch_result"] = dispatch_event_chain(conn, admission_id=admission_id, event_type="vital_sign", detail_id=out["detail_id"])
        return payload, out
    if event_type == "lab":
        lab_type = random.choice(["lactate", "creatinine", "abg", "wbc"])
        abnormal = random.choice(["normal", "high", "low"])
        payload = {
            "timestamp": sim_time,
            "source": "lab",
            "priority": "normal",
            "lab_type": lab_type,
            "value": Decimal(str(round(random.uniform(1.0, 6.0), 2))),
            "unit": "mmol/L" if lab_type == "lactate" else "unit",
            "abnormal_flag": abnormal,
        }
        body = LabEventCreate(**payload)
        out = write_lab(conn, admission_id, body)
        out["dispatch_result"] = dispatch_event_chain(conn, admission_id=admission_id, event_type="lab", detail_id=out["detail_id"])
        return payload, out
    payload = {
        "timestamp": sim_time,
        "source": "nurse",
        "priority": "normal",
        "intervention_type": random.choice(["fluid", "vasopressor", "ventilator_change"]),
        "description": random.choice(["fluid bolus", "norepinephrine titration", "adjust ventilator setting"]),
        "dosage": Decimal(str(round(random.uniform(0.1, 600), 2))),
        "unit": random.choice(["ml", "mcg/kg/min", "cmH2O"]),
    }
    body = InterventionEventCreate(**payload)
    out = write_intervention(conn, admission_id, body)
    out["dispatch_result"] = dispatch_event_chain(conn, admission_id=admission_id, event_type="intervention", detail_id=out["detail_id"])
    return payload, out


def reset_demo_auto(conn: Connection) -> DemoHospitalState:
    _ensure_demo_tables(conn)
    with conn.transaction():
        with conn.cursor() as cur:
            for table in [
                "demo_auto_timeline",
                "demo_auto_state",
                "orchestrator_runs",
                "agent_consumption_cursor",
                "agent_events",
                "agent_outputs",
                "alerts",
                "risk_assessments",
                "patient_state_snapshots",
                "patient_state_current",
                "patient_memory_events",
                "patient_memory",
                "intervention_pending",
                "events",
                "vital_sign_events",
                "lab_events",
                "intervention_events",
                "admissions",
                "beds",
                "patients",
                "audit_logs",
            ]:
                cur.execute(f"DELETE FROM {table}")
            now = _now_utc()
            cur.execute("INSERT INTO demo_auto_state (id, sim_time, step_index, updated_at) VALUES (1, %s, 0, NOW())", (now,))
    return get_demo_state(conn)


def get_demo_state(conn: Connection) -> DemoHospitalState:
    _ensure_demo_tables(conn)
    sim_time, step_index = _get_or_create_state(conn)
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM admissions WHERE status = 'active' AND scenario_tag = %s", (SIM_TAG,))
        active = int(cur.fetchone()["n"])
        cur.execute("SELECT COUNT(*) AS n FROM beds WHERE status = 'occupied'")
        occupied = int(cur.fetchone()["n"])
        cur.execute("SELECT COUNT(*) AS n FROM patients")
        total_patients = int(cur.fetchone()["n"])
        cur.execute(
            """
            SELECT id, step_index, sim_time, event_type, admission_id, payload, result, created_at
            FROM demo_auto_timeline ORDER BY step_index DESC LIMIT 10
            """
        )
        timeline = [dict(r) for r in cur.fetchall()]
    return DemoHospitalState(
        sim_time=sim_time,
        step_index=step_index,
        active_admissions=active,
        occupied_beds=occupied,
        total_patients=total_patients,
        recent_events=timeline,
    )


def list_timeline(conn: Connection, limit: int = 100) -> list[DemoTimelineItem]:
    _ensure_demo_tables(conn)
    limit = max(1, min(limit, 500))
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, step_index, sim_time, event_type, admission_id, payload, result, created_at
            FROM demo_auto_timeline ORDER BY step_index DESC LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    items: list[DemoTimelineItem] = []
    for r in rows:
        row = dict(r)
        row["payload"] = row.get("payload") or {}
        row["result"] = row.get("result") or {}
        items.append(DemoTimelineItem(**row))
    return items


def next_demo_step(conn: Connection) -> DemoNextResponse:
    """Advance simulation by SIM_STEP_MINUTES with a **ward batch tick**.

    Each tick may include:
    - 0–2 discharges among active demo patients
    - 0–2 admissions into empty demo beds
    - For **every** active demo patient after those mutations: one random clinical event
      (vital_sign / lab / intervention), each running the normal dispatch_event_chain.
    """
    _ensure_demo_tables(conn)
    with conn.transaction():
        step_wall_started_at = datetime.now(timezone.utc)
        sim_before, prev_index = _get_or_create_state(conn)
        if prev_index == 0:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO demo_auto_state (id, sim_time, step_index, updated_at)
                    VALUES (1, %s, 0, NOW())
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (sim_before,),
                )
        sim_after = sim_before + timedelta(minutes=SIM_STEP_MINUTES)
        step_index = prev_index + 1
        event_type = "batch_step"
        before_all = _counts(conn)

        active_start = _active_admissions(conn)
        anchor_before = active_start[0]["admission_id"] if active_start else None
        risk_before = _risk_snapshot(conn, anchor_before) if anchor_before else {}

        sub_events: list[dict[str, Any]] = []
        discharged_ids: list[str] = []

        # 0–2 discharges (need at least one other patient if discharging one of two)
        max_dis = min(2, len(active_start)) if active_start else 0
        nd = random.randint(0, max_dis) if max_dis > 0 else 0
        for _ in range(nd):
            active_now = _active_admissions(conn)
            pool = [a for a in active_now if a["admission_id"] not in discharged_ids]
            if not pool:
                break
            tgt = random.choice(pool)
            discharged_ids.append(cast(str, tgt["admission_id"]))
            wr = _discharge_random(conn, tgt, sim_after)
            sub_events.append({"type": "admission_discharge", "admission_id": tgt["admission_id"], "write_result": _json_safe(wr)})

        # 0–2 admissions into free demo beds
        na = random.randint(0, 2)
        admit_tags = ["", "a", "b"]
        for k in range(na):
            bed = _available_demo_bed(conn)
            if not bed:
                break
            sub_tag = admit_tags[k] if k < len(admit_tags) else f"x{k}"
            wr = _create_patient_bed_admission(conn, sim_after, step_index, sub_tag=sub_tag, bed_id=bed)
            sub_events.append({"type": "admission_create", "admission_id": wr["admission_id"], "write_result": _json_safe(wr)})

        # Every active patient: one random vital / lab / intervention
        active_clinical = _active_admissions(conn)
        random.shuffle(active_clinical)
        for adm in active_clinical:
            et = random.choice(["vital_sign", "lab", "intervention"])
            req, wr = _write_random_event(conn, adm, sim_after, et)
            sub_events.append(
                {
                    "type": et,
                    "admission_id": adm["admission_id"],
                    "request_payload": _json_safe(req),
                    "write_result": _json_safe(wr),
                }
            )

        _set_state(conn, sim_after, step_index)

        active_end = _active_admissions(conn)
        anchor_after: str | None = None
        if anchor_before and any(cast(str, a["admission_id"]) == anchor_before for a in active_end):
            anchor_after = anchor_before
        elif active_end:
            anchor_after = cast(str, active_end[0]["admission_id"])
        else:
            anchor_after = None

        admission_id = anchor_after
        request_payload: dict[str, Any] = {"batch": True, "sub_events": sub_events}
        write_result: dict[str, Any] = {
            "batch": True,
            "sub_event_count": len(sub_events),
            "sub_events": sub_events,
        }

        triggered_agents = _fetch_demo_triggered_agent_rows(
            conn, since_started_at=step_wall_started_at, scenario_tag=SIM_TAG, limit=500
        )
        after_all = _counts(conn)
        risk_after = _risk_snapshot(conn, anchor_after) if anchor_after else {}
        risk_change = DemoRiskChange(
            before=risk_before,
            after=risk_after,
            changed=_risk_changed(risk_before, risk_after),
        )
        workflow_trace = _fetch_agent_workflow_trace_demo_batch(
            conn, since_started_at=step_wall_started_at, scenario_tag=SIM_TAG
        )
        audit_log_ids = _fetch_audit_log_ids_demo_batch(conn, since_started_at=step_wall_started_at, scenario_tag=SIM_TAG)
        effects = DemoDbEffects(
            agent_outputs_added=after_all["agent_outputs"] - before_all["agent_outputs"],
            agent_events_added=after_all["agent_events"] - before_all["agent_events"],
            alerts_added=after_all["alerts"] - before_all["alerts"],
            risks_added=after_all["risks"] - before_all["risks"],
        )
        delta = {
            "event_type": event_type,
            "admission_id": admission_id,
            "sub_event_count": len(sub_events),
            "sub_event_types": [str(s.get("type")) for s in sub_events],
            "triggered_agent_names": sorted({str(a["producer_agent"]) for a in triggered_agents}),
            "triggered_event_types": sorted({str(a["event_type"]) for a in triggered_agents}),
            "agent_output_names": [str(item["agent_name"]) for item in workflow_trace],
            "risk_changed": risk_change.changed,
            "risk_before": risk_change.before.get("highest_severity"),
            "risk_after": risk_change.after.get("highest_severity"),
            "llm_used_by": [str(item["agent_name"]) for item in workflow_trace if item.get("llm", {}).get("llm_used")],
            "fallback_used_by": [str(item["agent_name"]) for item in workflow_trace if item.get("llm", {}).get("fallback_used")],
            "knowledge_cards_read": sorted(
                {
                    str(card_id)
                    for item in workflow_trace
                    for card_id in item.get("knowledge", {}).get("retrieved_card_ids", [])
                }
            ),
        }
        full_log = {
            "step_index": step_index,
            "sim_time_before": sim_before.isoformat(),
            "sim_time_after": sim_after.isoformat(),
            "event": {
                "event_type": event_type,
                "admission_id": admission_id,
                "request_payload": _json_safe(request_payload),
                "write_result": _json_safe(write_result),
            },
            "db_effects": effects.model_dump(mode="json"),
            "risk_change": risk_change.model_dump(mode="json"),
            "agent_workflow_trace": workflow_trace,
            "audit_log_ids": audit_log_ids,
            "human_review_required": True,
        }
        resp = DemoNextResponse(
            step_index=step_index,
            sim_time_before=sim_before,
            sim_time_after=sim_after,
            event_type=cast(Any, event_type),
            admission_id=admission_id,
            event_request_payload=_json_safe(request_payload),
            event_write_result=_json_safe(write_result),
            triggered_agents=triggered_agents,
            db_effects=effects,
            agent_delta_summary=delta,
            risk_change=risk_change,
            agent_workflow_trace=workflow_trace,
            audit_log_ids=audit_log_ids,
            full_observability_log=full_log,
        )
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO demo_auto_timeline (id, step_index, sim_time, event_type, admission_id, payload, result, created_at)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, NOW())
            """,
            (
                new_id("dtl"),
                step_index,
                sim_after,
                event_type,
                admission_id,
                Json(_json_safe(request_payload)),
                Json(_json_safe(resp.model_dump(mode="python"))),
            ),
        )
        cur.close()
    return resp
