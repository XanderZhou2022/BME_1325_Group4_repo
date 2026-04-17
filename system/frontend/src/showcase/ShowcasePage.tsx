import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { Admission, JsonObj } from "../types";
import "./showcase.css";

type OrchestratorStep = {
  step_name: string;
  admission_id: string;
  status: string;
  detail?: Record<string, unknown>;
};

type OrchestratorRun = {
  run_id: string;
  started_at?: string;
  finished_at?: string;
  target_admissions?: string[];
  step_results?: OrchestratorStep[];
};

type MetricCardProps = {
  title: string;
  value: string | number;
  sub?: string;
};

function MetricCard({ title, value, sub }: MetricCardProps) {
  return (
    <div className="scMetricCard">
      <div className="scMetricTitle">{title}</div>
      <div className="scMetricValue">{value}</div>
      {sub && <div className="scMetricSub">{sub}</div>}
    </div>
  );
}

function severityClass(sev: string): string {
  if (sev === "critical") return "critical";
  if (sev === "warning") return "warning";
  return "normal";
}

export default function ShowcasePage() {
  const [admissions, setAdmissions] = useState<Admission[]>([]);
  const [alerts, setAlerts] = useState<JsonObj[]>([]);
  const [latestWard, setLatestWard] = useState<JsonObj | null>(null);
  const [latestRun, setLatestRun] = useState<OrchestratorRun | null>(null);

  const [patients, setPatients] = useState<JsonObj[]>([]);
  const [events, setEvents] = useState<JsonObj[]>([]);
  const [orchestratorRuns, setOrchestratorRuns] = useState<OrchestratorRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string>("");

  const [selectedAdmissionId, setSelectedAdmissionId] = useState<string>("");
  const [patientState, setPatientState] = useState<JsonObj | null>(null);
  const [risks, setRisks] = useState<JsonObj[]>([]);
  const [vitals, setVitals] = useState<JsonObj[]>([]);
  const [interventions, setInterventions] = useState<JsonObj[]>([]);
  const [clinicalSummaries, setClinicalSummaries] = useState<JsonObj[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const activeAdmissions = useMemo(
    () => admissions.filter((a) => a.status === "active"),
    [admissions]
  );

  const criticalAlerts = useMemo(
    () => alerts.filter((a) => String(a.severity) === "critical").length,
    [alerts]
  );

  const selectedRun = useMemo(
    () => orchestratorRuns.find((r) => r.run_id === selectedRunId) ?? latestRun,
    [orchestratorRuns, selectedRunId, latestRun]
  );

  async function loadOverview() {
    setLoading(true);
    setError("");
    try {
      const [adTable, alertTable, outputTable, runTable, patientTable, eventTable] = await Promise.all([
        api.getTable("admissions", 500),
        api.getTable("alerts", 200),
        api.getTable("agent_outputs", 500),
        api.getTable("orchestrator_runs", 50),
        api.getTable("patients", 500),
        api.getTable("events", 500),
      ]);

      const adRows = adTable.rows as unknown as Admission[];
      setAdmissions(adRows);
      setAlerts(alertTable.rows);
      setPatients(patientTable.rows);
      setEvents(eventTable.rows);

      const wardRows = outputTable.rows
        .filter((r) => String(r.agent_name) === "ward_coordinator")
        .sort((a, b) => String(b.generated_at).localeCompare(String(a.generated_at)));
      setLatestWard(wardRows[0] ?? null);

      const runRows = (runTable.rows as unknown as OrchestratorRun[]).sort(
        (a, b) => String(b.started_at ?? "").localeCompare(String(a.started_at ?? ""))
      );
      setOrchestratorRuns(runRows);
      setLatestRun(runRows[0] ?? null);
      if (!selectedRunId && runRows.length > 0) {
        setSelectedRunId(runRows[0].run_id);
      }

      if (!selectedAdmissionId && adRows.length > 0) {
        const firstActive = adRows.find((r) => r.status === "active");
        setSelectedAdmissionId((firstActive ?? adRows[0]).admission_id);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "overview load failed");
    } finally {
      setLoading(false);
    }
  }

  async function loadPatient(admissionId: string) {
    if (!admissionId) return;
    try {
      const [state, r, v, i, cs] = await Promise.all([
        api.getCurrentState(admissionId).catch(() => null),
        api.getRisks(admissionId, 200),
        api.getVitals(admissionId, 200),
        api.getInterventions(admissionId, 200),
        api.getAgentOutputs(admissionId, "clinical_summary", 50),
      ]);
      setPatientState(state as JsonObj | null);
      setRisks(r);
      setVitals(v);
      setInterventions(i);
      setClinicalSummaries(cs);
    } catch (e) {
      setError(e instanceof Error ? e.message : "patient load failed");
    }
  }

  useEffect(() => {
    void loadOverview();
    const timer = window.setInterval(() => void loadOverview(), 15000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (selectedAdmissionId) {
      void loadPatient(selectedAdmissionId);
    }
  }, [selectedAdmissionId]);

  return (
    <div className="scPage">
      <header className="scTopBar">
        <div>
          <h1>ICU Live Showcase</h1>
          <p>Presentation view for operations and patient overview</p>
        </div>
        <div className="scTopActions">
          <a href="/">Back to Full Console</a>
          <button onClick={() => void loadOverview()}>{loading ? "Refreshing..." : "Refresh"}</button>
        </div>
      </header>

      {error && <div className="scError">{error}</div>}

      <section className="scMetrics">
        <MetricCard title="Active Beds" value={activeAdmissions.length} sub={`Total admissions: ${admissions.length}`} />
        <MetricCard title="Open Alerts" value={alerts.length} sub={`Critical: ${criticalAlerts}`} />
        <MetricCard
          title="Latest Pipeline Run"
          value={latestRun ? String(latestRun.run_id) : "N/A"}
          sub={latestRun ? String(latestRun.started_at) : "No run yet"}
        />
        <MetricCard
          title="Ward Load"
          value={String((latestWard?.payload as JsonObj | undefined)?.ward_load_indicator ?? "N/A")}
          sub="From ward_coordinator"
        />
      </section>

      <section className="scGrid2">
        <div className="scPanel">
          <h2>Complete Current Indicators</h2>
          <table className="scTable compact">
            <tbody>
              <tr><th>Current Vitals</th><td>{JSON.stringify(patientState?.current_vitals ?? {}, null, 2)}</td></tr>
              <tr><th>Active Problems</th><td>{JSON.stringify(patientState?.active_problems ?? [], null, 2)}</td></tr>
              <tr><th>Active Risks</th><td>{JSON.stringify(patientState?.active_risks ?? [], null, 2)}</td></tr>
              <tr><th>Latest Interventions</th><td>{JSON.stringify(patientState?.latest_interventions ?? [], null, 2)}</td></tr>
            </tbody>
          </table>
        </div>

        <div className="scPanel">
          <h2>Clinical Summary (All Latest)</h2>
          <div className="scScrollBox">
            <pre>{JSON.stringify(clinicalSummaries, null, 2)}</pre>
          </div>
        </div>
      </section>

      <section className="scGrid2">
        <div className="scPanel">
          <h2>Patient Board</h2>
          <table className="scTable">
            <thead>
              <tr>
                <th>Admission</th>
                <th>Bed</th>
                <th>Patient</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {admissions.map((a) => (
                <tr
                  key={a.admission_id}
                  className={selectedAdmissionId === a.admission_id ? "rowActive" : ""}
                  onClick={() => setSelectedAdmissionId(a.admission_id)}
                >
                  <td>{a.admission_id}</td>
                  <td>{a.bed_id}</td>
                  <td>{a.patient_id}</td>
                  <td>
                    <span className={`scStatus ${a.status === "active" ? "active" : "inactive"}`}>{a.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="scPanel">
          <h2>Selected Patient Snapshot</h2>
          <div className="scKeyValue">
            <span>Admission ID</span>
            <strong>{selectedAdmissionId || "N/A"}</strong>
          </div>
          <div className="scKeyValue">
            <span>Care Phase</span>
            <strong>{String((patientState?.care_phase as string | undefined) ?? "unknown")}</strong>
          </div>
          <div className="scKeyValue">
            <span>Current Risks</span>
            <strong>{Array.isArray(patientState?.active_risks) ? patientState?.active_risks.length : 0}</strong>
          </div>
          <div className="scDivider" />
          <h3>Risk Signals</h3>
          <div className="scChips">
            {risks.map((r, idx) => {
              const sev = String(r.severity ?? "low");
              return (
                <span key={`${String(r.id ?? idx)}_${idx}`} className={`scChip ${severityClass(sev)}`}>
                  {String(r.risk_type ?? "risk")} · {sev}
                </span>
              );
            })}
            {risks.length === 0 && <span className="scChip normal">No risks</span>}
          </div>
        </div>
      </section>

      <section className="scGrid2">
        <div className="scPanel">
          <h2>Patients Master Table</h2>
          <table className="scTable compact">
            <thead>
              <tr>
                <th>patient_id</th>
                <th>name</th>
                <th>gender</th>
                <th>age</th>
              </tr>
            </thead>
            <tbody>
              {patients.map((p, idx) => (
                <tr key={`${String(p.patient_id ?? idx)}_${idx}`}>
                  <td>{String(p.patient_id ?? "")}</td>
                  <td>{String(p.name ?? "-")}</td>
                  <td>{String(p.gender ?? "-")}</td>
                  <td>{String(p.age ?? "-")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="scPanel">
          <h2>Event Stream (events)</h2>
          <table className="scTable compact">
            <thead>
              <tr>
                <th>timestamp</th>
                <th>admission</th>
                <th>event_type</th>
                <th>source</th>
              </tr>
            </thead>
            <tbody>
              {events
                .slice()
                .sort((a, b) => String(b.timestamp ?? "").localeCompare(String(a.timestamp ?? "")))
                .map((e, idx) => (
                  <tr key={`${String(e.event_id ?? idx)}_${idx}`}>
                    <td>{String(e.timestamp ?? "")}</td>
                    <td>{String(e.admission_id ?? "")}</td>
                    <td>{String(e.event_type ?? "")}</td>
                    <td>{String(e.source ?? "")}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="scGrid2">
        <div className="scPanel">
          <h2>Orchestrator Runs</h2>
          <table className="scTable compact">
            <thead>
              <tr>
                <th>run_id</th>
                <th>started_at</th>
                <th>targets</th>
              </tr>
            </thead>
            <tbody>
              {orchestratorRuns.map((r) => (
                <tr key={r.run_id} className={selectedRun?.run_id === r.run_id ? "rowActive" : ""} onClick={() => setSelectedRunId(r.run_id)}>
                  <td>{r.run_id}</td>
                  <td>{String(r.started_at ?? "")}</td>
                  <td>{Array.isArray(r.target_admissions) ? r.target_admissions.join(",") : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="scPanel">
          <h2>Orchestrator Step Details</h2>
          <table className="scTable compact">
            <thead>
              <tr>
                <th>step</th>
                <th>admission</th>
                <th>status</th>
                <th>detail</th>
              </tr>
            </thead>
            <tbody>
              {(selectedRun?.step_results ?? []).map((st, idx) => (
                <tr key={`${st.step_name}_${st.admission_id}_${idx}`}>
                  <td>{st.step_name}</td>
                  <td>{st.admission_id}</td>
                  <td>
                    <span className={`scStatus ${st.status === "ok" ? "active" : "inactive"}`}>{st.status}</span>
                  </td>
                  <td>{JSON.stringify(st.detail ?? {})}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="scGrid2">
        <div className="scPanel">
          <h2>Recent Vitals</h2>
          <table className="scTable compact">
            <thead>
              <tr>
                <th>Time</th>
                <th>HR</th>
                <th>MAP</th>
                <th>SpO2</th>
              </tr>
            </thead>
            <tbody>
              {vitals.map((v, idx) => (
                <tr key={`${String(v.id ?? idx)}_${idx}`}>
                  <td>{String(v.timestamp ?? "")}</td>
                  <td>{String(v.heart_rate ?? "-")}</td>
                  <td>{String(v.mean_arterial_pressure ?? "-")}</td>
                  <td>{String(v.spo2 ?? "-")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="scPanel">
          <h2>Recent Interventions</h2>
          <table className="scTable compact">
            <thead>
              <tr>
                <th>Time</th>
                <th>Type</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              {interventions.map((it, idx) => (
                <tr key={`${String(it.id ?? idx)}_${idx}`}>
                  <td>{String(it.timestamp ?? "")}</td>
                  <td>{String(it.intervention_type ?? "-")}</td>
                  <td>{String(it.description ?? "-")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
