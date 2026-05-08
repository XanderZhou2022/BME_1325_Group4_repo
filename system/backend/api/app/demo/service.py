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

from .schemas import DemoDbEffects, DemoHospitalState, DemoNextResponse, DemoTimelineItem

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


def _create_patient_bed_admission(conn: Connection, sim_time: datetime, step_index: int) -> dict[str, Any]:
    pid = f"demo_p_{step_index:05d}"
    bid = f"demo_b_{((step_index - 1) % 20) + 1:02d}"
    aid = f"demo_adm_{step_index:05d}"
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
            (pid, f"DP{step_index:05d}", f"Demo Patient {step_index}", random.choice(["male", "female"]), random.randint(22, 88)),
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
                f"DEMO-{step_index:05d}",
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
        dispatch_event_chain(conn, admission_id=admission_id, event_type="vital_sign", detail_id=out["detail_id"])
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
        dispatch_event_chain(conn, admission_id=admission_id, event_type="lab", detail_id=out["detail_id"])
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
    dispatch_event_chain(conn, admission_id=admission_id, event_type="intervention", detail_id=out["detail_id"])
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


def _choose_event_type(active_count: int) -> str:
    if active_count == 0:
        return "admission_create"
    bucket = random.random()
    if bucket < 0.18:
        return "admission_create"
    if bucket < 0.30:
        return "admission_discharge"
    if bucket < 0.58:
        return "vital_sign"
    if bucket < 0.78:
        return "intervention"
    return "lab"


def next_demo_step(conn: Connection) -> DemoNextResponse:
    _ensure_demo_tables(conn)
    with conn.transaction():
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
        active = _active_admissions(conn)
        event_type = _choose_event_type(len(active))
        before_all = _counts(conn)
        admission_id: str | None = None
        request_payload: dict[str, Any] = {}
        write_result: dict[str, Any] = {}

        if event_type == "admission_create":
            write_result = _create_patient_bed_admission(conn, sim_after, step_index)
            admission_id = cast(str, write_result["admission_id"])
        elif event_type == "admission_discharge":
            target = random.choice(active)
            admission_id = cast(str, target["admission_id"])
            write_result = _discharge_random(conn, target, sim_after)
        else:
            target = random.choice(active)
            admission_id = cast(str, target["admission_id"])
            request_payload, write_result = _write_random_event(conn, target, sim_after, event_type)

        _set_state(conn, sim_after, step_index)
        cur = conn.cursor(row_factory=dict_row)
        triggered_agents: list[dict[str, Any]] = []
        if admission_id:
            cur.execute(
                """
                SELECT producer_agent, event_type, produced_at, payload
                FROM agent_events
                WHERE admission_id = %s AND produced_at >= %s
                ORDER BY produced_at DESC
                LIMIT 40
                """,
                (admission_id, sim_before),
            )
            triggered_agents = [dict(r) for r in cur.fetchall()]
        after_all = _counts(conn)
        effects = DemoDbEffects(
            agent_outputs_added=after_all["agent_outputs"] - before_all["agent_outputs"],
            agent_events_added=after_all["agent_events"] - before_all["agent_events"],
            alerts_added=after_all["alerts"] - before_all["alerts"],
            risks_added=after_all["risks"] - before_all["risks"],
        )
        delta = {
            "event_type": event_type,
            "admission_id": admission_id,
            "triggered_agent_names": sorted(list({str(a["producer_agent"]) for a in triggered_agents})),
            "triggered_event_types": sorted(list({str(a["event_type"]) for a in triggered_agents})),
        }
        resp = DemoNextResponse(
            step_index=step_index,
            sim_time_before=sim_before,
            sim_time_after=sim_after,
            event_type=cast(Any, event_type),
            admission_id=admission_id,
            event_request_payload=request_payload,
            event_write_result=write_result,
            triggered_agents=triggered_agents,
            db_effects=effects,
            agent_delta_summary=delta,
        )
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
                Json(_json_safe(resp.model_dump(mode="json"))),
            ),
        )
        cur.close()
    return resp
