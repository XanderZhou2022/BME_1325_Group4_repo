from __future__ import annotations

import os
import psycopg


DB_DSN = os.getenv("ICU_PG_DSN", "dbname=icu_agent user=zhou host=localhost port=5432")


DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS patients (
        patient_id TEXT PRIMARY KEY,
        patient_code TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        gender TEXT NOT NULL CHECK (gender IN ('male', 'female', 'other', 'unknown')),
        age INTEGER NOT NULL CHECK (age >= 0),
        date_of_birth DATE,
        contact TEXT,
        allergies JSONB NOT NULL DEFAULT '[]'::jsonb,
        chronic_conditions JSONB NOT NULL DEFAULT '[]'::jsonb,
        blood_type TEXT,
        baseline_profile JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS beds (
        bed_id TEXT PRIMARY KEY,
        bed_code TEXT NOT NULL UNIQUE,
        room_code TEXT NOT NULL,
        bed_type TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('occupied', 'empty', 'cleaning', 'maintenance')),
        notes TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS admissions (
        admission_id TEXT PRIMARY KEY,
        encounter_id TEXT NOT NULL UNIQUE,
        patient_id TEXT NOT NULL REFERENCES patients(patient_id),
        bed_id TEXT NOT NULL REFERENCES beds(bed_id),
        admission_code TEXT NOT NULL UNIQUE,
        admit_time TIMESTAMPTZ NOT NULL,
        discharge_time TIMESTAMPTZ,
        status TEXT NOT NULL CHECK (status IN ('active', 'discharged', 'expired', 'transferred')),
        encounter_status TEXT NOT NULL DEFAULT 'ADMITTED' CHECK (encounter_status IN (
            'ARRIVED', 'REGISTERED', 'TRIAGED', 'IN_CONSULTATION', 'IN_EXAM', 'IN_TREATMENT',
            'ADMITTED', 'DISCHARGED', 'COMPLETED', 'TRANSFERRING', 'CANCELLED', 'ERROR'
        )),
        primary_diagnosis TEXT NOT NULL,
        admission_reason TEXT NOT NULL,
        severity_on_admission TEXT NOT NULL CHECK (severity_on_admission IN ('stable', 'unstable', 'critical')),
        attending_team TEXT NOT NULL,
        scenario_tag TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        event_id TEXT PRIMARY KEY,
        admission_id TEXT NOT NULL REFERENCES admissions(admission_id),
        patient_id TEXT NOT NULL REFERENCES patients(patient_id),
        bed_id TEXT NOT NULL REFERENCES beds(bed_id),
        event_type TEXT NOT NULL CHECK (event_type IN ('vital_sign', 'lab', 'intervention', 'agent_output')),
        source TEXT NOT NULL CHECK (source IN ('monitor', 'lab', 'nurse', 'agent')),
        timestamp TIMESTAMPTZ NOT NULL,
        priority TEXT NOT NULL CHECK (priority IN ('low', 'normal', 'high', 'critical')),
        payload JSONB NOT NULL DEFAULT '{}'::jsonb
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS vital_sign_events (
        id TEXT PRIMARY KEY,
        admission_id TEXT NOT NULL REFERENCES admissions(admission_id),
        timestamp TIMESTAMPTZ NOT NULL,
        heart_rate INTEGER,
        mean_arterial_pressure NUMERIC(6, 2),
        systolic_bp NUMERIC(6, 2),
        diastolic_bp NUMERIC(6, 2),
        respiratory_rate INTEGER,
        temperature NUMERIC(4, 2),
        spo2 NUMERIC(5, 2),
        fio2 NUMERIC(4, 3),
        pao2 NUMERIC(6, 2),
        aado2 NUMERIC(8, 2),
        ph NUMERIC(4, 2),
        gcs INTEGER
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS lab_events (
        id TEXT PRIMARY KEY,
        admission_id TEXT NOT NULL REFERENCES admissions(admission_id),
        timestamp TIMESTAMPTZ NOT NULL,
        lab_type TEXT NOT NULL,
        value NUMERIC(12, 4) NOT NULL,
        unit TEXT NOT NULL,
        abnormal_flag TEXT NOT NULL CHECK (abnormal_flag IN ('normal', 'high', 'low'))
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS intervention_events (
        id TEXT PRIMARY KEY,
        admission_id TEXT NOT NULL REFERENCES admissions(admission_id),
        timestamp TIMESTAMPTZ NOT NULL,
        intervention_type TEXT NOT NULL CHECK (intervention_type IN ('fluid', 'vasopressor', 'ventilator_change')),
        description TEXT NOT NULL,
        dosage NUMERIC(12, 4),
        unit TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS intervention_pending (
        id TEXT PRIMARY KEY,
        admission_id TEXT NOT NULL REFERENCES admissions(admission_id),
        intervention_id TEXT NOT NULL UNIQUE REFERENCES intervention_events(id),
        status TEXT NOT NULL CHECK (status IN ('pending', 'ready_for_evaluation', 'completed', 'insufficient_data', 'expired')),
        observation_end_at TIMESTAMPTZ NOT NULL,
        last_evaluated_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS patient_state_current (
        admission_id TEXT PRIMARY KEY REFERENCES admissions(admission_id),
        patient_id TEXT NOT NULL REFERENCES patients(patient_id),
        bed_id TEXT NOT NULL REFERENCES beds(bed_id),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        current_vitals JSONB NOT NULL DEFAULT '{}'::jsonb,
        active_problems JSONB NOT NULL DEFAULT '[]'::jsonb,
        active_risks JSONB NOT NULL DEFAULT '[]'::jsonb,
        latest_interventions JSONB NOT NULL DEFAULT '[]'::jsonb,
        care_phase TEXT NOT NULL CHECK (care_phase IN ('stable', 'unstable', 'critical'))
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS patient_state_snapshots (
        id TEXT PRIMARY KEY,
        admission_id TEXT NOT NULL REFERENCES admissions(admission_id),
        timestamp TIMESTAMPTZ NOT NULL,
        state_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb
    );
    """,
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
    """,
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
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_outputs (
        output_id TEXT PRIMARY KEY,
        admission_id TEXT NOT NULL REFERENCES admissions(admission_id),
        patient_id TEXT NOT NULL REFERENCES patients(patient_id),
        bed_id TEXT NOT NULL REFERENCES beds(bed_id),
        agent_name TEXT NOT NULL,
        schema_version TEXT NOT NULL DEFAULT 'v1',
        output_type TEXT NOT NULL,
        generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        payload JSONB NOT NULL DEFAULT '{}'::jsonb
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_events (
        event_id TEXT PRIMARY KEY,
        admission_id TEXT NOT NULL REFERENCES admissions(admission_id),
        patient_id TEXT NOT NULL REFERENCES patients(patient_id),
        bed_id TEXT NOT NULL REFERENCES beds(bed_id),
        producer_agent TEXT NOT NULL,
        event_type TEXT NOT NULL,
        schema_version TEXT NOT NULL DEFAULT 'v1',
        produced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        output_id TEXT REFERENCES agent_outputs(output_id),
        payload JSONB NOT NULL DEFAULT '{}'::jsonb
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_consumption_cursor (
        consumer_agent TEXT NOT NULL,
        admission_id TEXT NOT NULL REFERENCES admissions(admission_id),
        last_event_id TEXT,
        last_event_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (consumer_agent, admission_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_registry (
        agent_name TEXT PRIMARY KEY,
        input_event_types JSONB NOT NULL DEFAULT '[]'::jsonb,
        output_event_type TEXT NOT NULL,
        schema_version TEXT NOT NULL DEFAULT 'v1',
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS orchestrator_runs (
        run_id TEXT PRIMARY KEY,
        started_at TIMESTAMPTZ NOT NULL,
        finished_at TIMESTAMPTZ NOT NULL,
        target_admissions JSONB NOT NULL DEFAULT '[]'::jsonb,
        step_results JSONB NOT NULL DEFAULT '[]'::jsonb
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS risk_assessments (
        id TEXT PRIMARY KEY,
        admission_id TEXT NOT NULL REFERENCES admissions(admission_id),
        timestamp TIMESTAMPTZ NOT NULL,
        risk_type TEXT NOT NULL,
        confidence NUMERIC(4, 3) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
        severity TEXT NOT NULL CHECK (severity IN ('low', 'warning', 'critical')),
        evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
        time_window TEXT NOT NULL,
        recommended_action TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS alerts (
        alert_id TEXT PRIMARY KEY,
        admission_id TEXT NOT NULL REFERENCES admissions(admission_id),
        patient_id TEXT NOT NULL REFERENCES patients(patient_id),
        bed_id TEXT NOT NULL REFERENCES beds(bed_id),
        alert_type TEXT NOT NULL,
        severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
        status TEXT NOT NULL CHECK (status IN ('open', 'acknowledged', 'closed')),
        source_agent TEXT NOT NULL,
        evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
        first_seen_at TIMESTAMPTZ NOT NULL,
        last_seen_at TIMESTAMPTZ NOT NULL
    );
    """,
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
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_action_requests (
        request_id TEXT PRIMARY KEY,
        admission_id TEXT NOT NULL REFERENCES admissions(admission_id),
        patient_id TEXT NOT NULL,
        bed_id TEXT NOT NULL,
        request_type TEXT NOT NULL CHECK (request_type IN ('lab', 'mdt_consultation')),
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'completed', 'failed')),
        requested_by_agent TEXT NOT NULL,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        source_output_id TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        fulfilled_at TIMESTAMPTZ,
        fulfillment_detail JSONB
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS ward_priority_snapshots (
        snapshot_id TEXT PRIMARY KEY,
        generated_at TIMESTAMPTZ NOT NULL,
        occupied_beds INT,
        critical_patients INT,
        high_risk_patients INT,
        new_deteriorations INT,
        priority_queue JSONB NOT NULL DEFAULT '[]'::jsonb,
        merged_alerts JSONB NOT NULL DEFAULT '[]'::jsonb,
        ward_summary TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS ward_priority_events (
        event_id TEXT PRIMARY KEY,
        generated_at TIMESTAMPTZ NOT NULL,
        bed_id TEXT,
        patient_id TEXT,
        priority_level TEXT,
        priority_score INT,
        reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
        source_risk_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS llm_audit_logs (
        audit_log_id TEXT PRIMARY KEY,
        timestamp TIMESTAMPTZ NOT NULL,
        task_name TEXT NOT NULL,
        agent_name TEXT,
        patient_id TEXT,
        admission_id TEXT,
        prompt_template TEXT,
        model TEXT,
        llm_enabled BOOLEAN NOT NULL DEFAULT FALSE,
        schema_valid BOOLEAN,
        safety_valid BOOLEAN,
        fallback_used BOOLEAN NOT NULL DEFAULT FALSE,
        error TEXT,
        retrieved_card_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        input_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        raw_output TEXT,
        parsed_output JSONB,
        record JSONB NOT NULL DEFAULT '{}'::jsonb
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_llm_audit_logs_timestamp ON llm_audit_logs (timestamp DESC);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_llm_audit_logs_admission_ts
        ON llm_audit_logs (admission_id, timestamp DESC)
        WHERE admission_id IS NOT NULL;
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        id TEXT PRIMARY KEY,
        timestamp TIMESTAMPTZ NOT NULL,
        actor TEXT NOT NULL CHECK (actor IN ('agent', 'system', 'user')),
        actor_id TEXT NOT NULL,
        action_type TEXT NOT NULL CHECK (action_type IN ('create_event', 'update_state', 'run_agent')),
        target_type TEXT NOT NULL,
        target_id TEXT NOT NULL,
        input JSONB NOT NULL DEFAULT '{}'::jsonb,
        output JSONB NOT NULL DEFAULT '{}'::jsonb
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS idempotency_keys (
        key TEXT PRIMARY KEY,
        route TEXT NOT NULL,
        response_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
]


# Backfill columns when upgrading an older database (safe no-ops if already present).
ALTER_UPGRADE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS llm_audit_logs (
        audit_log_id TEXT PRIMARY KEY,
        timestamp TIMESTAMPTZ NOT NULL,
        task_name TEXT NOT NULL,
        agent_name TEXT,
        patient_id TEXT,
        admission_id TEXT,
        prompt_template TEXT,
        model TEXT,
        llm_enabled BOOLEAN NOT NULL DEFAULT FALSE,
        schema_valid BOOLEAN,
        safety_valid BOOLEAN,
        fallback_used BOOLEAN NOT NULL DEFAULT FALSE,
        error TEXT,
        retrieved_card_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        input_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        raw_output TEXT,
        parsed_output JSONB,
        record JSONB NOT NULL DEFAULT '{}'::jsonb
    );
  """,
    """
    CREATE INDEX IF NOT EXISTS idx_llm_audit_logs_timestamp ON llm_audit_logs (timestamp DESC);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_llm_audit_logs_admission_ts
        ON llm_audit_logs (admission_id, timestamp DESC)
        WHERE admission_id IS NOT NULL;
    """,
    """
    ALTER TABLE patients ADD COLUMN IF NOT EXISTS contact TEXT;
    ALTER TABLE patients ADD COLUMN IF NOT EXISTS allergies JSONB NOT NULL DEFAULT '[]'::jsonb;
    ALTER TABLE patients ADD COLUMN IF NOT EXISTS chronic_conditions JSONB NOT NULL DEFAULT '[]'::jsonb;
    ALTER TABLE patients ADD COLUMN IF NOT EXISTS blood_type TEXT;
    """,
    """
    ALTER TABLE patients DROP CONSTRAINT IF EXISTS patients_gender_check;
    ALTER TABLE patients ADD CONSTRAINT patients_gender_check
      CHECK (gender IN ('male', 'female', 'other', 'unknown'));
    """,
    """
    ALTER TABLE admissions ADD COLUMN IF NOT EXISTS encounter_id TEXT;
    ALTER TABLE admissions ADD COLUMN IF NOT EXISTS encounter_status TEXT NOT NULL DEFAULT 'ADMITTED';
    """,
]


def main() -> None:
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            for ddl in DDL_STATEMENTS:
                cur.execute(ddl)
            for block in ALTER_UPGRADE_STATEMENTS:
                cur.execute(block)

            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN (
                      'patients', 'beds', 'admissions', 'events', 'vital_sign_events',
                      'lab_events', 'intervention_events', 'patient_state_current',
                      'intervention_pending',
                      'patient_memory', 'patient_memory_events',
                      'patient_state_snapshots', 'agent_outputs', 'agent_events', 'clinical_summaries',
                      'ward_priority_snapshots', 'ward_priority_events',
                      'agent_consumption_cursor', 'agent_registry',
                      'orchestrator_runs', 'risk_assessments', 'alerts', 'llm_audit_logs', 'audit_logs'
                  )
                ORDER BY table_name;
                """
            )
            rows = cur.fetchall()

    print("Core tables ready:")
    for (table_name,) in rows:
        print(f"- {table_name}")


if __name__ == "__main__":
    main()

