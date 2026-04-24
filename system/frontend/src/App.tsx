import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import ShowcasePage from "./showcase/ShowcasePage";
import ShowcaseDetailPage from "./showcase/ShowcaseDetailPage";
import AutoDemoPage from "./showcase/AutoDemoPage";
import type { Admission, JsonObj } from "./types";

type PipelineStep = {
  step_name: string;
  admission_id: string;
  status: string;
  detail?: Record<string, unknown>;
};

type PipelineResult = {
  run_id: string;
  target_admissions: string[];
  step_results: PipelineStep[];
};

type LoadState = "idle" | "loading" | "ok" | "error";

function safeStr(v: unknown): string {
  return typeof v === "string" ? v : JSON.stringify(v);
}

export default function App() {
  if (typeof window !== "undefined" && window.location.pathname.startsWith("/auto")) {
    return <AutoDemoPage />;
  }
  if (typeof window !== "undefined" && window.location.pathname.startsWith("/showcase_detail")) {
    return <ShowcaseDetailPage />;
  }
  if (typeof window !== "undefined" && window.location.pathname.startsWith("/showcase")) {
    return <ShowcasePage />;
  }
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [error, setError] = useState<string>("");

  const [admissions, setAdmissions] = useState<Admission[]>([]);
  const [selectedAdmissionId, setSelectedAdmissionId] = useState<string>("");

  const [currentState, setCurrentState] = useState<JsonObj | null>(null);
  const [vitals, setVitals] = useState<JsonObj[]>([]);
  const [interventions, setInterventions] = useState<JsonObj[]>([]);
  const [risks, setRisks] = useState<JsonObj[]>([]);
  const [clinicalSummaries, setClinicalSummaries] = useState<JsonObj[]>([]);
  const [wardCoordinatorHistory, setWardCoordinatorHistory] = useState<JsonObj[]>([]);

  const [tableList, setTableList] = useState<string[]>([]);
  const [selectedTable, setSelectedTable] = useState<string>("");
  const [tableRows, setTableRows] = useState<JsonObj[]>([]);
  const [tableTotal, setTableTotal] = useState<number>(0);

  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [pipelineResult, setPipelineResult] = useState<PipelineResult | null>(null);

  const [newAdmission, setNewAdmission] = useState({
    admission_id: "",
    patient_id: "",
    bed_id: "",
    admission_code: "",
    admit_time: new Date().toISOString(),
    primary_diagnosis: "",
    admission_reason: "",
    severity_on_admission: "unstable",
    attending_team: "ICU-A",
    scenario_tag: "frontend",
  });

  const [statusForm, setStatusForm] = useState({
    admission_id: "",
    status: "discharged",
    discharge_time: new Date().toISOString(),
  });

  const [vitalForm, setVitalForm] = useState({
    admission_id: "",
    timestamp: new Date().toISOString(),
    source: "monitor",
    priority: "normal",
    heart_rate: "",
    mean_arterial_pressure: "",
    systolic_bp: "",
    diastolic_bp: "",
    respiratory_rate: "",
    temperature: "",
    spo2: "",
    fio2: "",
    pao2: "",
    aado2: "",
    ph: "",
    gcs: "",
  });

  const [interventionForm, setInterventionForm] = useState({
    admission_id: "",
    timestamp: new Date().toISOString(),
    intervention_type: "fluid",
    description: "",
    dosage: "",
    unit: "ml",
    source: "nurse",
    priority: "normal",
  });

  const occupiedBeds = useMemo(() => admissions.filter((a) => a.status === "active").length, [admissions]);

  async function loadAdmissionsAndWard() {
    setLoadState("loading");
    setError("");
    try {
      const admissionsTable = await api.getTable("admissions", 500);
      const rows = admissionsTable.rows as unknown as Admission[];
      setAdmissions(rows);

      const wardTable = await api.getTable("agent_outputs", 300);
      const wardRows = wardTable.rows.filter((row) => row.agent_name === "ward_coordinator");
      setWardCoordinatorHistory(wardRows);

      setLoadState("ok");
    } catch (e) {
      setLoadState("error");
      setError(e instanceof Error ? e.message : "Load failed");
    }
  }

  async function loadAdmissionDetail(admissionId: string) {
    if (!admissionId) return;
    try {
      const [state, v, it, r, cs] = await Promise.all([
        api.getCurrentState(admissionId).catch(() => null),
        api.getVitals(admissionId, 50),
        api.getInterventions(admissionId, 50),
        api.getRisks(admissionId, 50),
        api.getAgentOutputs(admissionId, "clinical_summary", 20),
      ]);
      setCurrentState(state as JsonObj | null);
      setVitals(v);
      setInterventions(it);
      setRisks(r);
      setClinicalSummaries(cs);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Detail load failed");
    }
  }

  async function loadTableList() {
    try {
      const tables = await api.listTables();
      setTableList(tables);
      if (!selectedTable && tables.length > 0) {
        setSelectedTable(tables[0]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Table list load failed");
    }
  }

  async function loadTableData(table: string) {
    if (!table) return;
    try {
      const preview = await api.getTable(table, 100);
      setTableRows(preview.rows);
      setTableTotal(preview.total_rows);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Table preview load failed");
    }
  }

  useEffect(() => {
    void loadAdmissionsAndWard();
    void loadTableList();
    const timer = window.setInterval(() => {
      void loadAdmissionsAndWard();
      if (selectedAdmissionId) void loadAdmissionDetail(selectedAdmissionId);
      if (selectedTable) void loadTableData(selectedTable);
    }, 15000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!selectedAdmissionId && admissions.length > 0) {
      setSelectedAdmissionId(admissions[0].admission_id);
    }
  }, [admissions, selectedAdmissionId]);

  useEffect(() => {
    if (selectedAdmissionId) {
      void loadAdmissionDetail(selectedAdmissionId);
      setVitalForm((prev) => ({ ...prev, admission_id: selectedAdmissionId }));
      setInterventionForm((prev) => ({ ...prev, admission_id: selectedAdmissionId }));
      setStatusForm((prev) => ({ ...prev, admission_id: selectedAdmissionId }));
    }
  }, [selectedAdmissionId]);

  useEffect(() => {
    if (selectedTable) {
      void loadTableData(selectedTable);
    }
  }, [selectedTable]);

  async function submitNewAdmission() {
    try {
      await api.createAdmission(newAdmission as unknown as JsonObj);
      await loadAdmissionsAndWard();
      setNewAdmission((prev) => ({ ...prev, admission_id: "", patient_id: "", bed_id: "", admission_code: "" }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Create admission failed");
    }
  }

  async function submitStatusUpdate() {
    if (!statusForm.admission_id) return;
    try {
      await api.updateAdmissionStatus(statusForm.admission_id, {
        status: statusForm.status,
        discharge_time: statusForm.discharge_time,
      });
      await loadAdmissionsAndWard();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Status update failed");
    }
  }

  async function submitVital() {
    if (!vitalForm.admission_id) return;
    try {
      await api.postVital(vitalForm.admission_id, {
        timestamp: vitalForm.timestamp,
        source: vitalForm.source,
        priority: vitalForm.priority,
        heart_rate: vitalForm.heart_rate ? Number(vitalForm.heart_rate) : null,
        mean_arterial_pressure: vitalForm.mean_arterial_pressure ? Number(vitalForm.mean_arterial_pressure) : null,
        systolic_bp: vitalForm.systolic_bp ? Number(vitalForm.systolic_bp) : null,
        diastolic_bp: vitalForm.diastolic_bp ? Number(vitalForm.diastolic_bp) : null,
        respiratory_rate: vitalForm.respiratory_rate ? Number(vitalForm.respiratory_rate) : null,
        temperature: vitalForm.temperature ? Number(vitalForm.temperature) : null,
        spo2: vitalForm.spo2 ? Number(vitalForm.spo2) : null,
        fio2: vitalForm.fio2 ? Number(vitalForm.fio2) : null,
        pao2: vitalForm.pao2 ? Number(vitalForm.pao2) : null,
        aado2: vitalForm.aado2 ? Number(vitalForm.aado2) : null,
        ph: vitalForm.ph ? Number(vitalForm.ph) : null,
        gcs: vitalForm.gcs ? Number(vitalForm.gcs) : null,
      });
      await loadAdmissionDetail(vitalForm.admission_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Post vital failed");
    }
  }

  async function submitIntervention() {
    if (!interventionForm.admission_id) return;
    try {
      await api.postIntervention(interventionForm.admission_id, {
        timestamp: interventionForm.timestamp,
        intervention_type: interventionForm.intervention_type,
        description: interventionForm.description,
        dosage: interventionForm.dosage ? Number(interventionForm.dosage) : null,
        unit: interventionForm.unit,
        source: interventionForm.source,
        priority: interventionForm.priority,
      });
      await loadAdmissionDetail(interventionForm.admission_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Post intervention failed");
    }
  }

  async function runPipelineAll() {
    setPipelineRunning(true);
    setError("");
    try {
      const result = await api.runPipeline({ run_all_active: true, memory_window_hours: 24, top_k: 5 });
      setPipelineResult(result as unknown as PipelineResult);
      if (selectedAdmissionId) {
        await loadAdmissionDetail(selectedAdmissionId);
      }
      await loadAdmissionsAndWard();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Run pipeline failed");
    } finally {
      setPipelineRunning(false);
    }
  }

  return (
    <div className="page">
      <header className="header">
        <h1>ICU Multi-Agent Dashboard</h1>
        <div className="meta">API: {api.base}</div>
        <div className="meta">Occupancy: {occupiedBeds}</div>
        <button onClick={() => void loadAdmissionsAndWard()}>Refresh</button>
        <button onClick={() => void runPipelineAll()} disabled={pipelineRunning}>
          {pipelineRunning ? "Pipeline Running..." : "Run Full Pipeline"}
        </button>
        <a href="/showcase" className="showcaseLink">Open Showcase</a>
        <a href="/showcase_detail" className="showcaseLink">Open Showcase Detail</a>
        <a href="/auto" className="showcaseLink">Open Auto Demo</a>
      </header>

      {loadState === "loading" && <p>Loading...</p>}
      {error && <p className="error">{error}</p>}

      <section className="card">
        <h2>Pipeline Execution</h2>
        {!pipelineResult && <p>No pipeline run result yet. Click "Run Full Pipeline".</p>}
        {pipelineResult && (
          <>
            <p>
              <strong>Run ID:</strong> {pipelineResult.run_id} | <strong>Admissions:</strong>{" "}
              {pipelineResult.target_admissions.join(", ")}
            </p>
            <pre>
              {JSON.stringify(
                {
                  ok_steps: pipelineResult.step_results.filter((s) => s.status === "ok").length,
                  error_steps: pipelineResult.step_results.filter((s) => s.status === "error").length,
                  skipped_steps: pipelineResult.step_results.filter((s) => s.status === "skipped").length,
                  errors: pipelineResult.step_results
                    .filter((s) => s.status === "error")
                    .map((s) => ({ step: s.step_name, admission: s.admission_id, detail: s.detail })),
                },
                null,
                2
              )}
            </pre>
          </>
        )}
      </section>

      <section className="grid2">
        <div className="card">
          <h2>Current Admissions</h2>
          <ul className="list">
            {admissions.map((a) => (
              <li key={a.admission_id}>
                <button
                  className={a.admission_id === selectedAdmissionId ? "selected" : ""}
                  onClick={() => setSelectedAdmissionId(a.admission_id)}
                >
                  {a.admission_id} | bed={a.bed_id} | patient={a.patient_id} | {a.status}
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="card">
          <h2>Patient Detail</h2>
          <div><strong>Current State</strong></div>
          <pre>{currentState ? JSON.stringify(currentState, null, 2) : "N/A"}</pre>
          <div><strong>Risk Sentinel</strong></div>
          <pre>{JSON.stringify(risks.slice(0, 10), null, 2)}</pre>
          <div><strong>Clinical Summary</strong></div>
          <pre>{JSON.stringify(clinicalSummaries.slice(0, 5), null, 2)}</pre>
        </div>
      </section>

      <section className="grid2">
        <div className="card">
          <h2>Monitor History (Vitals)</h2>
          <pre>{JSON.stringify(vitals.slice(0, 20), null, 2)}</pre>
        </div>
        <div className="card">
          <h2>Treatment History (Interventions)</h2>
          <pre>{JSON.stringify(interventions.slice(0, 20), null, 2)}</pre>
        </div>
      </section>

      <section className="grid2">
        <div className="card">
          <h2>Ward Coordinator History</h2>
          <pre>{JSON.stringify(wardCoordinatorHistory.slice(0, 15), null, 2)}</pre>
        </div>
        <div className="card">
          <h2>Data Input</h2>

          <h3>1) Add Admission</h3>
          <div className="formGrid">
            <input placeholder="admission_id" value={newAdmission.admission_id} onChange={(e) => setNewAdmission({ ...newAdmission, admission_id: e.target.value })} />
            <input placeholder="patient_id" value={newAdmission.patient_id} onChange={(e) => setNewAdmission({ ...newAdmission, patient_id: e.target.value })} />
            <input placeholder="bed_id" value={newAdmission.bed_id} onChange={(e) => setNewAdmission({ ...newAdmission, bed_id: e.target.value })} />
            <input placeholder="admission_code" value={newAdmission.admission_code} onChange={(e) => setNewAdmission({ ...newAdmission, admission_code: e.target.value })} />
            <input placeholder="diagnosis" value={newAdmission.primary_diagnosis} onChange={(e) => setNewAdmission({ ...newAdmission, primary_diagnosis: e.target.value })} />
            <input placeholder="reason" value={newAdmission.admission_reason} onChange={(e) => setNewAdmission({ ...newAdmission, admission_reason: e.target.value })} />
            <button onClick={() => void submitNewAdmission()}>Create Admission</button>
          </div>

          <h3>2) Discharge/Expired</h3>
          <div className="formGrid">
            <input placeholder="admission_id" value={statusForm.admission_id} onChange={(e) => setStatusForm({ ...statusForm, admission_id: e.target.value })} />
            <select value={statusForm.status} onChange={(e) => setStatusForm({ ...statusForm, status: e.target.value })}>
              <option value="discharged">discharged</option>
              <option value="expired">expired</option>
              <option value="transferred">transferred</option>
              <option value="active">active</option>
            </select>
            <button onClick={() => void submitStatusUpdate()}>Update Status</button>
          </div>

          <h3>3) Post Vital (bedside_monitor input)</h3>
          <div className="formGrid">
            <input placeholder="admission_id" value={vitalForm.admission_id} onChange={(e) => setVitalForm({ ...vitalForm, admission_id: e.target.value })} />
            <input placeholder="heart_rate" value={vitalForm.heart_rate} onChange={(e) => setVitalForm({ ...vitalForm, heart_rate: e.target.value })} />
            <input placeholder="mean_arterial_pressure" value={vitalForm.mean_arterial_pressure} onChange={(e) => setVitalForm({ ...vitalForm, mean_arterial_pressure: e.target.value })} />
            <input placeholder="systolic_bp" value={vitalForm.systolic_bp} onChange={(e) => setVitalForm({ ...vitalForm, systolic_bp: e.target.value })} />
            <input placeholder="diastolic_bp" value={vitalForm.diastolic_bp} onChange={(e) => setVitalForm({ ...vitalForm, diastolic_bp: e.target.value })} />
            <input placeholder="respiratory_rate" value={vitalForm.respiratory_rate} onChange={(e) => setVitalForm({ ...vitalForm, respiratory_rate: e.target.value })} />
            <input placeholder="temperature" value={vitalForm.temperature} onChange={(e) => setVitalForm({ ...vitalForm, temperature: e.target.value })} />
            <input placeholder="spo2" value={vitalForm.spo2} onChange={(e) => setVitalForm({ ...vitalForm, spo2: e.target.value })} />
            <input placeholder="fio2 (0-1)" value={vitalForm.fio2} onChange={(e) => setVitalForm({ ...vitalForm, fio2: e.target.value })} />
            <input placeholder="pao2" value={vitalForm.pao2} onChange={(e) => setVitalForm({ ...vitalForm, pao2: e.target.value })} />
            <input placeholder="aado2" value={vitalForm.aado2} onChange={(e) => setVitalForm({ ...vitalForm, aado2: e.target.value })} />
            <input placeholder="ph" value={vitalForm.ph} onChange={(e) => setVitalForm({ ...vitalForm, ph: e.target.value })} />
            <input placeholder="gcs" value={vitalForm.gcs} onChange={(e) => setVitalForm({ ...vitalForm, gcs: e.target.value })} />
            <button onClick={() => void submitVital()}>Submit Vital</button>
          </div>

          <h3>4) Post Intervention (intervention_tracker input)</h3>
          <div className="formGrid">
            <input placeholder="admission_id" value={interventionForm.admission_id} onChange={(e) => setInterventionForm({ ...interventionForm, admission_id: e.target.value })} />
            <input placeholder="description" value={interventionForm.description} onChange={(e) => setInterventionForm({ ...interventionForm, description: e.target.value })} />
            <select value={interventionForm.intervention_type} onChange={(e) => setInterventionForm({ ...interventionForm, intervention_type: e.target.value })}>
              <option value="fluid">fluid</option>
              <option value="vasopressor">vasopressor</option>
              <option value="ventilator_change">ventilator_change</option>
            </select>
            <button onClick={() => void submitIntervention()}>Submit Intervention</button>
          </div>
        </div>
      </section>

      <section className="card">
        <h2>Database Live Viewer</h2>
        <div className="inline">
          <select value={selectedTable} onChange={(e) => setSelectedTable(e.target.value)}>
            {tableList.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
          <button onClick={() => selectedTable && void loadTableData(selectedTable)}>Load Table</button>
          <span>Total rows: {tableTotal}</span>
        </div>
        <pre>{safeStr(tableRows.slice(0, 50))}</pre>
      </section>
    </div>
  );
}
