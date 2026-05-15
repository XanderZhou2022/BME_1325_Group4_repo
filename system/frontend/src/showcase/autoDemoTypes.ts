import type { JsonObj } from "../types";

/** Full `POST /demo/auto/next` payload after contract unwrap */
export type DemoNextFull = {
  step_index: number;
  sim_time_before: string;
  sim_time_after: string;
  event_type: string;
  admission_id?: string | null;
  event_request_payload?: JsonObj;
  event_write_result?: JsonObj;
  triggered_agents?: JsonObj[];
  db_effects?: JsonObj;
  agent_delta_summary?: JsonObj;
  risk_change?: JsonObj;
  agent_workflow_trace?: AgentWorkflowTraceItem[];
  audit_log_ids?: string[];
  full_observability_log?: JsonObj;
};

export type AgentWorkflowTraceItem = {
  agent_name?: string;
  output_id?: string;
  output_type?: string;
  generated_at?: string;
  received_context?: {
    admission_id?: string;
    patient_id?: string;
    bed_id?: string;
  };
  knowledge?: JsonObj;
  judgment?: JsonObj;
  llm?: JsonObj;
  human_review_required?: boolean;
  forbidden_use_reminder?: unknown;
};

export type WardPriorityQueueItem = {
  rank?: number;
  admission_id?: string;
  patient_id?: string;
  bed_id?: string;
  care_phase?: string;
  priority_score?: number;
  priority_level?: string;
  reason?: unknown;
  suggested_attention?: string;
  summary_hint?: string;
  rationale?: string;
  active_risks?: unknown[];
  human_review_required?: boolean;
};

export type AdmissionBoardRow = {
  admission_id: string;
  patient_id: string;
  bed_id: string;
  status: string;
  severity_on_admission?: string;
  primary_diagnosis?: string;
  admission_reason?: string;
  admit_time?: string;
  care_phase?: string;
  risk_count: number;
  updated_at?: string;
};

export type UiMode = "presentation" | "debug";

const STORAGE_KEY = "icu_auto_demo_ui_mode";

export function loadUiMode(): UiMode {
  if (typeof window === "undefined") return "presentation";
  const v = window.localStorage.getItem(STORAGE_KEY);
  return v === "debug" ? "debug" : "presentation";
}

export function saveUiMode(mode: UiMode): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, mode);
}
