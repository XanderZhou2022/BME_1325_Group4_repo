import type { AgentWorkflowTraceItem } from "./autoDemoTypes";
import type { JsonObj } from "../types";

export type LlmTraceRow = {
  agent_name: string;
  admission_id: string;
  bed_id: string;
  patient_id: string;
  llm_used: boolean;
  fallback_used: boolean;
  audit_log_id: string;
  status: "success" | "fallback" | "skipped";
  status_label: string;
  response_preview: string;
};

const NO_LLM_AGENTS = new Set(["bedside_monitor", "intervention_tracker"]);

function previewFromLlm(llm: JsonObj): string {
  const fields = (llm.generated_text_fields ?? {}) as JsonObj;
  const parts: string[] = [];
  for (const [key, val] of Object.entries(fields)) {
    if (val == null || val === "") continue;
    const text = typeof val === "string" ? val : JSON.stringify(val);
    parts.push(`${key}: ${text.slice(0, 280)}${text.length > 280 ? "…" : ""}`);
  }
  return parts.join("\n") || "（无生成文本字段）";
}

function statusFor(agent: string, llm: JsonObj): { status: LlmTraceRow["status"]; status_label: string } {
  const used = Boolean(llm.llm_used);
  const fallback = Boolean(llm.fallback_used);
  if (NO_LLM_AGENTS.has(agent)) {
    return { status: "skipped", status_label: "设计为不调用 LLM（仅知识库/规则）" };
  }
  if (used && !fallback) {
    return { status: "success", status_label: "LLM 成功" };
  }
  if (fallback) {
    return { status: "fallback", status_label: "LLM 失败或未启用，已走 fallback" };
  }
  return { status: "skipped", status_label: "本步未调用 LLM" };
}

export function buildLlmTraceRows(trace: AgentWorkflowTraceItem[] | undefined): LlmTraceRow[] {
  if (!trace?.length) return [];
  return trace.map((item) => {
    const ctx = item.received_context ?? {};
    const llm = (item.llm ?? {}) as JsonObj;
    const agent = String(item.agent_name ?? "—");
    const { status, status_label } = statusFor(agent, llm);
    const admission_id = String(ctx.admission_id ?? "");
    return {
      agent_name: agent,
      admission_id: admission_id || (agent === "ward_coordinator" ? "（全病房）" : "—"),
      bed_id: String(ctx.bed_id ?? (agent === "ward_coordinator" ? "—" : "—")),
      patient_id: String(ctx.patient_id ?? (agent === "ward_coordinator" ? "—" : "—")),
      llm_used: Boolean(llm.llm_used),
      fallback_used: Boolean(llm.fallback_used),
      audit_log_id: String(llm.audit_log_id ?? "—"),
      status,
      status_label,
      response_preview: previewFromLlm(llm),
    };
  });
}

export function groupLlmTraceByAdmission(rows: LlmTraceRow[]): Map<string, LlmTraceRow[]> {
  const m = new Map<string, LlmTraceRow[]>();
  for (const row of rows) {
    const key = row.admission_id || row.bed_id;
    const list = m.get(key) ?? [];
    list.push(row);
    m.set(key, list);
  }
  return m;
}
