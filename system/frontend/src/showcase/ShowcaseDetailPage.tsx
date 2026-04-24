import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { JsonObj } from "../types";
import "./showcase.css";

type StepResult = {
  step_name: string;
  admission_id: string;
  status: "ok" | "skipped" | "error" | string;
  started_at?: string;
  finished_at?: string;
  detail?: JsonObj;
  input_sources?: string[];
  input_window?: string | null;
};

type OrchestratorRun = {
  run_id: string;
  started_at?: string;
  finished_at?: string;
  target_admissions?: string[];
  step_results?: StepResult[];
};

function pretty(v: unknown): string {
  return JSON.stringify(v ?? {}, null, 2);
}

export default function ShowcaseDetailPage() {
  const [runs, setRuns] = useState<OrchestratorRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [runDetail, setRunDetail] = useState<OrchestratorRun | null>(null);
  const [agentOutputsByAdmission, setAgentOutputsByAdmission] = useState<Record<string, JsonObj[]>>({});
  const [agentEventsByAdmission, setAgentEventsByAdmission] = useState<Record<string, JsonObj[]>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const selectedRun = useMemo(
    () => runDetail ?? runs.find((r) => r.run_id === selectedRunId) ?? null,
    [runDetail, runs, selectedRunId]
  );

  async function triggerDemoRun() {
    setLoading(true);
    setError("");
    try {
      await api.runPipeline({ run_all_active: true, top_k: 10, memory_window_hours: 24 });
      await loadRuns();
    } catch (e) {
      setError(e instanceof Error ? e.message : "trigger demo-run failed");
    } finally {
      setLoading(false);
    }
  }

  async function loadRuns() {
    setLoading(true);
    setError("");
    try {
      // Keep data source aligned with ShowcasePage to avoid endpoint drift.
      const table = await api.getTable("orchestrator_runs", 50);
      const list = (table.rows as unknown as OrchestratorRun[]).sort((a, b) =>
        String(b.started_at ?? "").localeCompare(String(a.started_at ?? ""))
      );
      setRuns(list);
      if (!selectedRunId && list.length > 0) {
        setSelectedRunId(String(list[0].run_id));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "load runs failed");
    } finally {
      setLoading(false);
    }
  }

  async function loadRunDetail(runId: string) {
    if (!runId) return;
    setLoading(true);
    setError("");
    try {
      // Use table preview as primary source; step_results is stored directly there.
      const table = await api.getTable("orchestrator_runs", 100);
      const row = table.rows.find((r) => String(r.run_id) === runId) as OrchestratorRun | undefined;
      const detail = row ?? ((await api.getOrchestratorRun(runId)) as unknown as OrchestratorRun);
      setRunDetail(detail);
      const admissions = Array.from(new Set((detail.step_results ?? []).map((s) => s.admission_id).filter((a) => a && a !== "global")));
      const outputsEntries = await Promise.all(
        admissions.map(async (admissionId) => {
          const out = await api.getAgentOutputs(admissionId, undefined, 100);
          return [admissionId, out] as const;
        })
      );
      const eventsEntries = await Promise.all(
        admissions.map(async (admissionId) => {
          const out = await api.getAgentEvents(admissionId, undefined, 150);
          return [admissionId, out] as const;
        })
      );
      setAgentOutputsByAdmission(Object.fromEntries(outputsEntries));
      setAgentEventsByAdmission(Object.fromEntries(eventsEntries));
    } catch (e) {
      setError(e instanceof Error ? e.message : "load run detail failed");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadRuns();
  }, []);

  useEffect(() => {
    if (selectedRunId) {
      void loadRunDetail(selectedRunId);
    }
  }, [selectedRunId]);

  return (
    <div className="scPage">
      <header className="scTopBar">
        <div>
          <h1>ICU Showcase Detail</h1>
          <p>Step-by-step trace: agent input, process, output, persistence</p>
        </div>
        <div className="scTopActions">
          <a href="/showcase">Back to Showcase</a>
          <a href="/">Back to Full Console</a>
          <button onClick={() => void loadRuns()}>{loading ? "Refreshing..." : "Refresh"}</button>
        </div>
      </header>

      {error && <div className="scError">{error}</div>}

      <section className="scGrid2">
        <div className="scPanel">
          <h2>Orchestrator Runs</h2>
          {runs.length === 0 && (
            <div className="scError" style={{ marginBottom: 12 }}>
              No orchestrator run data yet. Click the button below to trigger a demo run.
            </div>
          )}
          {runs.length === 0 && (
            <button onClick={() => void triggerDemoRun()} disabled={loading}>
              {loading ? "Running Demo..." : "One-click Demo Run"}
            </button>
          )}
          <table className="scTable compact">
            <thead>
              <tr>
                <th>run_id</th>
                <th>started_at</th>
                <th>targets</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.run_id} className={selectedRunId === r.run_id ? "rowActive" : ""} onClick={() => setSelectedRunId(r.run_id)}>
                  <td>{r.run_id}</td>
                  <td>{String(r.started_at ?? "")}</td>
                  <td>{Array.isArray(r.target_admissions) ? r.target_admissions.join(", ") : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="scPanel">
          <h2>Run Summary</h2>
          <pre>
            {pretty(
              selectedRun
                ? {
                    run_id: selectedRun.run_id,
                    started_at: selectedRun.started_at,
                    finished_at: selectedRun.finished_at,
                    target_admissions: selectedRun.target_admissions ?? [],
                    step_count: (selectedRun.step_results ?? []).length,
                    ok: (selectedRun.step_results ?? []).filter((s) => s.status === "ok").length,
                    skipped: (selectedRun.step_results ?? []).filter((s) => s.status === "skipped").length,
                    error: (selectedRun.step_results ?? []).filter((s) => s.status === "error").length,
                  }
                : {}
            )}
          </pre>
        </div>
      </section>

      <section className="scPanel">
        <h2>Step-by-Step Details</h2>
        {(selectedRun?.step_results ?? []).map((st, idx) => {
          const admissionId = st.admission_id;
          const outputs = admissionId && admissionId !== "global" ? agentOutputsByAdmission[admissionId] ?? [] : [];
          const events = admissionId && admissionId !== "global" ? agentEventsByAdmission[admissionId] ?? [] : [];
          const relatedOutputs = outputs
            .filter((o) => String(o.agent_name) === st.step_name)
            .slice(0, 3);
          const relatedEvents = events
            .filter((e) => String(e.producer_agent) === st.step_name)
            .slice(0, 8);

          return (
            <div className="scPanel" key={`${st.step_name}_${admissionId}_${idx}`}>
              <h3>
                Step {idx + 1}: {st.step_name} ({admissionId}) - {st.status}
              </h3>
              <table className="scTable compact">
                <tbody>
                  <tr>
                    <th>What agent did</th>
                    <td>{st.step_name} executed as part of orchestrator run.</td>
                  </tr>
                  <tr>
                    <th>Read input data</th>
                    <td>{pretty({ input_sources: st.input_sources ?? [], input_window: st.input_window ?? null })}</td>
                  </tr>
                  <tr>
                    <th>Step detail output</th>
                    <td>{pretty(st.detail ?? {})}</td>
                  </tr>
                  <tr>
                    <th>Stored (agent_outputs)</th>
                    <td>{pretty(relatedOutputs)}</td>
                  </tr>
                  <tr>
                    <th>Event bus (agent_events)</th>
                    <td>{pretty(relatedEvents)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          );
        })}
      </section>
    </div>
  );
}
