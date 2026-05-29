import type { JsonObj } from "../types";
import type { DemoNextFull } from "./autoDemoTypes";

function str(v: unknown): string {
  if (v === null || v === undefined) return "";
  return String(v);
}

export function resolveCurrentEventBedId(lastStep: DemoNextFull | null, admissions: { admission_id: string; bed_id: string }[]): string {
  if (!lastStep) return "";
  const trace = lastStep.agent_workflow_trace?.[0]?.received_context?.bed_id;
  if (trace) return str(trace);
  const aid = lastStep.admission_id;
  if (aid) {
    const row = admissions.find((a) => a.admission_id === aid);
    if (row) return row.bed_id;
  }
  const ta = lastStep.triggered_agents?.[0] as JsonObj | undefined;
  const fromTa = ta?.bed_id ?? (ta?.payload as JsonObj)?.bed_id;
  if (fromTa) return str(fromTa);
  return "";
}

export function buildStepNarrativeLines(lastStep: DemoNextFull | null): string[] {
  if (!lastStep) return ["No step run yet. Use Next Step to advance the simulation."];
  const lines: string[] = [];
  const et = str(lastStep.event_type);
  const aid = str(lastStep.admission_id ?? "");
  if (et === "batch_step") {
    const p = (lastStep.event_request_payload ?? {}) as Record<string, unknown>;
    const subs = p.sub_events as unknown[] | undefined;
    const n = Array.isArray(subs) ? subs.length : 0;
    lines.push(`Ward batch tick: ${n} sub-event(s). Anchor admission for risk snapshot: ${aid || "N/A"}.`);
    if (Array.isArray(subs) && subs.length > 0) {
      const types: Record<string, number> = {};
      for (const s of subs) {
        if (s && typeof s === "object" && "type" in s) {
          const t = str((s as Record<string, unknown>).type);
          types[t] = (types[t] ?? 0) + 1;
        }
      }
      lines.push(`Mix: ${Object.entries(types)
        .map(([k, v]) => `${k}×${v}`)
        .join(", ")}.`);
    }
  } else {
    lines.push(`Event: ${et}${aid ? ` for admission ${aid}.` : "."}`);
  }

  const db = lastStep.db_effects as JsonObj | undefined;
  if (db) {
    lines.push(
      `Database: +${str(db.agent_outputs_added)} agent outputs, +${str(db.agent_events_added)} agent events, +${str(db.alerts_added)} alerts, +${str(db.risks_added)} risk rows.`
    );
  }

  const names = (lastStep.agent_delta_summary as JsonObj)?.triggered_agent_names;
  if (Array.isArray(names) && names.length) {
    lines.push(`Agents touched this step: ${names.join(", ")}.`);
  }

  const rc = lastStep.risk_change as JsonObj | undefined;
  if (rc) {
    const before = (rc.before as JsonObj)?.highest_severity;
    const after = (rc.after as JsonObj)?.highest_severity;
    if (before !== undefined || after !== undefined) {
      lines.push(`Risk snapshot: highest severity ${str(before)} → ${str(after)}${rc.changed ? " (changed)." : "."}`);
    }
  }

  const dispatch = (lastStep.event_write_result as JsonObj)?.dispatch_result;
  if (dispatch != null) {
    lines.push(`Orchestrator dispatch: recorded in event_write_result.dispatch_result (see Debug panel).`);
  }

  const trace = lastStep.agent_workflow_trace ?? [];
  if (trace.length) {
    const llmOn = trace.filter((t) => (t.llm as JsonObj)?.llm_used).map((t) => str(t.agent_name));
    if (llmOn.length) lines.push(`LLM-assisted outputs: ${llmOn.join(", ")}.`);
    else lines.push("This step used knowledge/rules; no LLM generation flag on trace items (or LLM disabled).");
  }

  lines.push("All clinical-facing outputs require human review before operational use.");
  return lines;
}
