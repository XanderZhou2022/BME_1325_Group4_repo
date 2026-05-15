import type { JsonObj } from "../types";
import type { AgentWorkflowTraceItem, DemoNextFull } from "./autoDemoTypes";

export type PipelineAgentId =
  | "bedside_monitor"
  | "intervention_tracker"
  | "patient_memory"
  | "risk_sentinel"
  | "clinical_summary"
  | "ward_coordinator"
  | "compassion_family_communication";

export type PipelineNodeStatus =
  | "not_triggered"
  | "started"
  | "pending"
  | "not_enough_data"
  | "completed"
  | "failed";

const ORDER: PipelineAgentId[] = [
  "bedside_monitor",
  "intervention_tracker",
  "patient_memory",
  "risk_sentinel",
  "clinical_summary",
  "ward_coordinator",
  "compassion_family_communication",
];

function normAgent(s: string): string {
  return String(s || "").trim();
}

function triggeredRows(lastStep: DemoNextFull | null): JsonObj[] {
  return (lastStep?.triggered_agents ?? []) as JsonObj[];
}

function traceByAgent(lastStep: DemoNextFull | null): Map<string, AgentWorkflowTraceItem> {
  const m = new Map<string, AgentWorkflowTraceItem>();
  for (const t of lastStep?.agent_workflow_trace ?? []) {
    const name = normAgent(String(t.agent_name ?? ""));
    if (name) m.set(name, t);
  }
  return m;
}

function rowsForAgent(rows: JsonObj[], agent: string): JsonObj[] {
  return rows.filter((r) => normAgent(String(r.producer_agent ?? "")) === agent);
}

export function inferPipelineStatuses(lastStep: DemoNextFull | null): { id: PipelineAgentId; status: PipelineNodeStatus; hint: string }[] {
  const rows = triggeredRows(lastStep);
  const traceMap = traceByAgent(lastStep);

  return ORDER.map((id) => {
    const myRows = rowsForAgent(rows, id);
    const trace = traceMap.get(id);

    if (trace) {
      if (id === "intervention_tracker") {
        const ot = String(trace.output_type ?? "");
        const j = trace.judgment as JsonObj | undefined;
        const label = String(j?.response_label ?? "");
        if (ot.includes("pending") || label.includes("not_enough") || label === "not_enough_data") {
          return { id, status: "not_enough_data" as const, hint: label || "pending evaluation" };
        }
      }
      return { id, status: "completed" as const, hint: "output written" };
    }

    const started = myRows.some((r) => String(r.event_type ?? "").includes(".started") || String(r.event_type ?? "").endsWith("_started"));
    const pending = myRows.some(
      (r) =>
        String(r.event_type ?? "").includes("pending") ||
        String(r.event_type ?? "").includes("evaluation_pending")
    );
    const readyLike = myRows.some((r) => /ready|completed/i.test(String(r.event_type ?? "")));

    if (pending) return { id, status: "pending" as const, hint: "awaiting data" };
    if (readyLike) return { id, status: "completed" as const, hint: "event indicates output" };
    if (started) return { id, status: "started" as const, hint: "in progress" };
    if (myRows.length > 0) return { id, status: "started" as const, hint: "agent activity without output trace" };

    return { id, status: "not_triggered" as const, hint: "—" };
  });
}
