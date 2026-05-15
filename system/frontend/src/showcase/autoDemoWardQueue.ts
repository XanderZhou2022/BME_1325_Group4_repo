import type { JsonObj } from "../types";
import type { AdmissionBoardRow, DemoNextFull, WardPriorityQueueItem, AgentWorkflowTraceItem } from "./autoDemoTypes";

export type WardQueueSource = "last_step_trace" | "ward_api" | "fallback";

function asQueue(v: unknown): WardPriorityQueueItem[] {
  if (!Array.isArray(v)) return [];
  return v as WardPriorityQueueItem[];
}

/** Ward judgment may include priority_queue when trace was built from ward payload */
export function extractQueueFromLastStep(lastStep: DemoNextFull | null): { queue: WardPriorityQueueItem[]; source: WardQueueSource } | null {
  if (!lastStep?.agent_workflow_trace) return null;
  const ward = lastStep.agent_workflow_trace.find((t) => String(t.agent_name) === "ward_coordinator");
  if (!ward) return null;
  const j = ward.judgment as JsonObj | undefined;
  let pq = j?.priority_queue;
  if (!Array.isArray(pq) || pq.length === 0) {
    const full = lastStep.full_observability_log as JsonObj | undefined;
    const wt = (full?.agent_workflow_trace as AgentWorkflowTraceItem[] | undefined)?.find(
      (t) => String(t.agent_name) === "ward_coordinator"
    );
    const j2 = wt?.judgment as JsonObj | undefined;
    pq = j2?.priority_queue;
  }
  const q = asQueue(pq);
  if (!q.length) return null;
  return { queue: q, source: "last_step_trace" };
}

export function pickLatestWardPayload(rowsByAdmission: JsonObj[][]): { queue: WardPriorityQueueItem[]; generatedAt: string } | null {
  let bestAt = 0;
  let bestPayload: JsonObj | null = null;
  let bestAtStr = "";
  for (const rows of rowsByAdmission) {
    for (const row of rows) {
      const p = row as JsonObj;
      const ga = String(p.generated_at ?? "");
      const t = ga ? new Date(ga).getTime() : 0;
      const pl = p.payload as JsonObj | undefined;
      const pq = pl?.priority_queue;
      if (!Array.isArray(pq) || pq.length === 0) continue;
      if (t >= bestAt) {
        bestAt = t;
        bestPayload = pl ?? {};
        bestAtStr = ga;
      }
    }
  }
  if (!bestPayload) return null;
  return { queue: asQueue(bestPayload.priority_queue), generatedAt: bestAtStr };
}

function careScore(phase: string | undefined): number {
  if (phase === "critical") return 100;
  if (phase === "unstable") return 50;
  return 10;
}

export function buildFallbackQueue(board: AdmissionBoardRow[]): { queue: WardPriorityQueueItem[]; source: WardQueueSource } {
  const sorted = [...board].sort((a, b) => {
    const ds = careScore(b.care_phase) - careScore(a.care_phase);
    if (ds !== 0) return ds;
    if (b.risk_count !== a.risk_count) return b.risk_count - a.risk_count;
    return String(b.updated_at ?? "").localeCompare(String(a.updated_at ?? ""));
  });
  const queue: WardPriorityQueueItem[] = sorted.map((row, idx) => ({
    rank: idx + 1,
    admission_id: row.admission_id,
    patient_id: row.patient_id,
    bed_id: row.bed_id,
    care_phase: row.care_phase,
    priority_score: careScore(row.care_phase) + row.risk_count * 10,
    priority_level: row.care_phase === "critical" ? "immediate" : row.care_phase === "unstable" ? "urgent" : "routine",
    reason: [
      `care_phase=${row.care_phase ?? "unknown"}`,
      `active_risks=${row.risk_count}`,
      row.primary_diagnosis ? `diagnosis=${row.primary_diagnosis}` : "",
    ].filter(Boolean),
    suggested_attention: row.risk_count > 0 ? "Review risks and latest vitals" : "Routine monitoring",
    summary_hint: `${row.bed_id}: ${row.primary_diagnosis ?? "ICU patient"}`,
    human_review_required: true,
  }));
  return { queue, source: "fallback" };
}

export function queueSignature(queue: WardPriorityQueueItem[]): string {
  return queue.map((q) => `${q.rank}:${q.admission_id}`).join("|");
}
