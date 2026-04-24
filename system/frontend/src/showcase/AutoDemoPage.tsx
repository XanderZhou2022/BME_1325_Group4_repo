import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { JsonObj } from "../types";
import "./showcase.css";

type DemoState = {
  sim_time: string;
  step_index: number;
  active_admissions: number;
  occupied_beds: number;
  total_patients: number;
  recent_events: JsonObj[];
};

type DemoAdmission = {
  admission_id: string;
  patient_id: string;
  bed_id: string;
  status: string;
  severity_on_admission?: string;
  primary_diagnosis?: string;
  admission_reason?: string;
  admit_time?: string;
};

type DemoNext = {
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
};

function getSeverityClass(sev: string | undefined): string {
  if (sev === "critical") return "critical";
  if (sev === "unstable") return "warning";
  return "normal";
}

export default function AutoDemoPage() {
  const [state, setState] = useState<DemoState | null>(null);
  const [timeline, setTimeline] = useState<JsonObj[]>([]);
  const [lastStep, setLastStep] = useState<DemoNext | null>(null);
  const [admissions, setAdmissions] = useState<DemoAdmission[]>([]);
  const [selectedAdmissionId, setSelectedAdmissionId] = useState<string>("");
  const [selectedPatientState, setSelectedPatientState] = useState<JsonObj | null>(null);
  const [selectedVitals, setSelectedVitals] = useState<JsonObj[]>([]);
  const [selectedInterventions, setSelectedInterventions] = useState<JsonObj[]>([]);
  const [selectedClinicalSummaries, setSelectedClinicalSummaries] = useState<JsonObj[]>([]);
  const [selectedTrackerOutputs, setSelectedTrackerOutputs] = useState<JsonObj[]>([]);
  const [selectedClinicalEvents, setSelectedClinicalEvents] = useState<JsonObj[]>([]);
  const [selectedTrackerEvents, setSelectedTrackerEvents] = useState<JsonObj[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const activeAdmissions = useMemo(
    () => admissions.filter((a) => a.status === "active"),
    [admissions]
  );

  const agentOps = useMemo(
    () => (lastStep?.triggered_agents ?? []) as JsonObj[],
    [lastStep]
  );

  const filteredAgentOps = useMemo(() => {
    if (!selectedAgent) return agentOps;
    return agentOps.filter((a) => String(a.producer_agent ?? "") === selectedAgent);
  }, [agentOps, selectedAgent]);

  const agentNames = useMemo(
    () => Array.from(new Set(agentOps.map((a) => String(a.producer_agent ?? "")))).filter(Boolean),
    [agentOps]
  );

  async function loadAdmissionDetail(admissionId: string) {
    if (!admissionId) {
      setSelectedPatientState(null);
      setSelectedVitals([]);
      setSelectedInterventions([]);
      setSelectedClinicalSummaries([]);
      setSelectedTrackerOutputs([]);
      setSelectedClinicalEvents([]);
      setSelectedTrackerEvents([]);
      return;
    }
    const [st, vitals, interventions, summaries, tracker, csEvents, itEvents] = await Promise.all([
      api.getCurrentState(admissionId).catch(() => null),
      api.getVitals(admissionId, 50).catch(() => []),
      api.getInterventions(admissionId, 50).catch(() => []),
      api.getAgentOutputs(admissionId, "clinical_summary", 20).catch(() => []),
      api.getAgentOutputs(admissionId, "intervention_tracker", 20).catch(() => []),
      api.getAgentEvents(admissionId, "clinical_summary", 20).catch(() => []),
      api.getAgentEvents(admissionId, "intervention_tracker", 20).catch(() => []),
    ]);
    setSelectedPatientState((st as JsonObj) ?? null);
    setSelectedVitals((vitals as JsonObj[]) ?? []);
    setSelectedInterventions((interventions as JsonObj[]) ?? []);
    setSelectedClinicalSummaries((summaries as JsonObj[]) ?? []);
    setSelectedTrackerOutputs((tracker as JsonObj[]) ?? []);
    setSelectedClinicalEvents((csEvents as JsonObj[]) ?? []);
    setSelectedTrackerEvents((itEvents as JsonObj[]) ?? []);
  }

  async function refreshAll() {
    try {
      const [st, tl, admissionTable] = await Promise.all([
        api.demoAutoState(),
        api.demoAutoTimeline(80),
        api.getTable("admissions", 200),
      ]);
      setState(st as unknown as DemoState);
      setTimeline(((tl as JsonObj).items as JsonObj[]) ?? []);
      const rows = (admissionTable.rows as unknown as DemoAdmission[])
        .filter((r) => String((r as JsonObj).scenario_tag ?? "") === "demo_auto")
        .sort((a, b) => String(b.admit_time ?? "").localeCompare(String(a.admit_time ?? "")));
      setAdmissions(rows);
      if (rows.length > 0) {
        const stillExists = rows.some((r) => r.admission_id === selectedAdmissionId && r.status === "active");
        if (!selectedAdmissionId || !stillExists) {
          setSelectedAdmissionId(rows.find((r) => r.status === "active")?.admission_id ?? "");
        }
      } else {
        setSelectedAdmissionId("");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "load failed");
    }
  }

  async function resetDemo() {
    setLoading(true);
    setError("");
    try {
      await api.demoAutoReset();
      setLastStep(null);
      await refreshAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "reset failed");
    } finally {
      setLoading(false);
    }
  }

  async function nextStep() {
    setLoading(true);
    setError("");
    try {
      const out = (await api.demoAutoNext()) as unknown as DemoNext;
      setLastStep(out);
      setSelectedAgent("");
      await refreshAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "next step failed");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refreshAll();
  }, []);

  useEffect(() => {
    void loadAdmissionDetail(selectedAdmissionId);
  }, [selectedAdmissionId]);

  return (
    <div className="scPage">
      <header className="scTopBar">
        <div>
          <h1>Auto ICU Demo</h1>
          <p>Empty hospital -&gt; random events -&gt; live multi-agent reactions</p>
        </div>
        <div className="scTopActions">
          <a href="/">Back to Console</a>
          <button onClick={() => void resetDemo()} disabled={loading}>{loading ? "Working..." : "Reset Hospital"}</button>
          <button onClick={() => void nextStep()} disabled={loading}>{loading ? "Working..." : "Next Step (+5min)"}</button>
        </div>
      </header>

      {error && <div className="scError">{error}</div>}

      <section className="scMetrics">
        <div className="scMetricCard">
          <div className="scMetricTitle">Sim Time</div>
          <div className="scMetricValue">{state?.sim_time ?? "N/A"}</div>
        </div>
        <div className="scMetricCard">
          <div className="scMetricTitle">Step Index</div>
          <div className="scMetricValue">{state?.step_index ?? 0}</div>
        </div>
        <div className="scMetricCard">
          <div className="scMetricTitle">Active Admissions</div>
          <div className="scMetricValue">{state?.active_admissions ?? 0}</div>
        </div>
        <div className="scMetricCard">
          <div className="scMetricTitle">Occupied Beds</div>
          <div className="scMetricValue">{state?.occupied_beds ?? 0}</div>
        </div>
      </section>

      <section className="scGrid2">
        <div className="scPanel">
          <h2>Hospital Situation (Patients Board)</h2>
          {activeAdmissions.length === 0 && <div>No active patients in hospital.</div>}
          <div className="patientGrid">
            {activeAdmissions.map((a) => (
              <button
                key={a.admission_id}
                className={`patientCard ${getSeverityClass(a.severity_on_admission)} ${selectedAdmissionId === a.admission_id ? "selected" : ""}`}
                onClick={() => setSelectedAdmissionId(a.admission_id)}
              >
                <div className="patientCardTop">
                  <strong>{a.bed_id}</strong>
                  <span>{a.severity_on_admission ?? "stable"}</span>
                </div>
                <div>Patient: {a.patient_id}</div>
                <div>Admission: {a.admission_id}</div>
                <div className="patientCardSub">{a.primary_diagnosis ?? "N/A"}</div>
              </button>
            ))}
          </div>
        </div>

        <div className="scPanel">
          <h2>Current Event (Last Step)</h2>
          <pre>{JSON.stringify(lastStep ?? {}, null, 2)}</pre>
        </div>
      </section>

      <section className="scGrid2">
        <div className="scPanel">
          <h2>Selected Patient Detail</h2>
          {!selectedAdmissionId && <div>Select a patient card to view detail.</div>}
          {selectedAdmissionId && (
            <>
              <div className="scKeyValue"><span>Admission</span><strong>{selectedAdmissionId}</strong></div>
              <div className="scKeyValue">
                <span>Current Risks</span>
                <strong>{Array.isArray(selectedPatientState?.active_risks) ? selectedPatientState?.active_risks.length : 0}</strong>
              </div>
              <div className="scKeyValue">
                <span>Care Phase</span>
                <strong>{String(selectedPatientState?.care_phase ?? "unknown")}</strong>
              </div>
              <div className="scDivider" />
              <h3>Recent Vitals</h3>
              <pre>{JSON.stringify(selectedVitals.slice(0, 15), null, 2)}</pre>
              <h3>Recent Interventions</h3>
              <pre>{JSON.stringify(selectedInterventions.slice(0, 10), null, 2)}</pre>
              <h3>Clinical Summary Agent Output</h3>
              <pre>{JSON.stringify(selectedClinicalSummaries.slice(0, 5), null, 2)}</pre>
              {selectedClinicalSummaries.length === 0 && (
                <pre>
                  {JSON.stringify(
                    {
                      message: "No clinical_summary output for this patient yet.",
                      latest_events: selectedClinicalEvents.slice(0, 3).map((e) => ({
                        event_type: e.event_type,
                        produced_at: e.produced_at,
                        payload: e.payload,
                      })),
                    },
                    null,
                    2
                  )}
                </pre>
              )}
              <h3>Intervention Tracker Output</h3>
              <pre>{JSON.stringify(selectedTrackerOutputs.slice(0, 5), null, 2)}</pre>
              {selectedTrackerOutputs.length === 0 && (
                <pre>
                  {JSON.stringify(
                    {
                      message: "No intervention_tracker output for this patient yet.",
                      hint: "This agent usually needs intervention events and enough post-window data.",
                      latest_events: selectedTrackerEvents.slice(0, 3).map((e) => ({
                        event_type: e.event_type,
                        produced_at: e.produced_at,
                        payload: e.payload,
                      })),
                    },
                    null,
                    2
                  )}
                </pre>
              )}
            </>
          )}
        </div>

        <div className="scPanel">
          <h2>Timeline (Latest First)</h2>
          <pre>{JSON.stringify(timeline.slice(0, 20), null, 2)}</pre>
        </div>
      </section>

      <section className="scPanel">
        <h2>Agent Reactions (Current Step)</h2>
        <div className="scTopActions" style={{ marginBottom: 10 }}>
          <span>Filter agent:</span>
          <select value={selectedAgent} onChange={(e) => setSelectedAgent(e.target.value)}>
            <option value="">All</option>
            {agentNames.map((name) => (
              <option value={name} key={name}>{name}</option>
            ))}
          </select>
        </div>
        <div className="scKeyValue">
          <span>Triggered Agent Names</span>
          <strong>{JSON.stringify(lastStep?.agent_delta_summary?.triggered_agent_names ?? [])}</strong>
        </div>
        <div className="scKeyValue">
          <span>DB Effects</span>
          <strong>{JSON.stringify(lastStep?.db_effects ?? {})}</strong>
        </div>
        <div className="scDivider" />
        {filteredAgentOps.length === 0 && <div>No agent operations for this step.</div>}
        {filteredAgentOps.map((op, idx) => (
          <div className="reactionItem" key={`${String(op.producer_agent ?? "agent")}_${idx}`}>
            <div className="reactionHeader">
              <strong>{String(op.producer_agent ?? "")}</strong>
              <span>{String(op.event_type ?? "")}</span>
              <span>{String(op.produced_at ?? "")}</span>
            </div>
            <pre>{JSON.stringify(op.payload ?? {}, null, 2)}</pre>
          </div>
        ))}
      </section>
    </div>
  );
}
