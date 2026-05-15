import type { JsonObj } from "../types";

export function reactionSummary(op: JsonObj): string {
  const p = (op.payload ?? {}) as JsonObj;
  const parts: string[] = [];
  const u = p.urgency_level ?? p.overall_risk_level;
  if (u) parts.push(`urgency/risk: ${String(u)}`);
  const rl = p.response_label ?? p.status;
  if (rl) parts.push(`status: ${String(rl)}`);
  const ol = p.one_line_status;
  if (ol) parts.push(String(ol).slice(0, 120));
  return parts.join(" · ") || String(op.event_type ?? "agent event");
}

export function reactionEvidence(op: JsonObj): string[] {
  const p = (op.payload ?? {}) as JsonObj;
  const out: string[] = [];
  const flags = p.abnormal_flags ?? p.new_or_worsening_flags;
  if (Array.isArray(flags) && flags.length) out.push(`flags: ${flags.slice(0, 5).join(", ")}`);
  const risks = p.active_risks;
  if (Array.isArray(risks) && risks.length) out.push(`active risks: ${risks.length}`);
  if (p.intervention_type) out.push(`intervention: ${String(p.intervention_type)}`);
  return out.slice(0, 6);
}

export function timelineOneLine(row: JsonObj): string {
  const et = String(row.event_type ?? "");
  const aid = String(row.admission_id ?? "");
  if (et === "batch_step") {
    const p = (row.payload ?? {}) as JsonObj;
    const subs = p.sub_events as JsonObj[] | undefined;
    const n = Array.isArray(subs) ? subs.length : 0;
    return `Batch ward tick (${n} sub-events) · anchor ${aid || "—"}`;
  }
  if (et === "admission_create") return `New admission ${aid || "—"}`;
  if (et === "admission_discharge") return `Discharge ${aid || "—"}`;
  if (et === "vital_sign") return `Vital sign update ${aid || "—"}`;
  if (et === "lab") return `Lab result ${aid || "—"}`;
  if (et === "intervention") return `Intervention ${aid || "—"}`;
  return `${et} ${aid}`.trim();
}
