import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../api";
import type { JsonObj } from "../types";
import { buildStepNarrativeLines, resolveCurrentEventBedId } from "./autoDemoNarrative";
import { inferPipelineStatuses } from "./autoDemoPipeline";
import { reactionEvidence, reactionSummary, timelineOneLine } from "./autoDemoReactionHelpers";
import type { AdmissionBoardRow, DemoNextFull, UiMode, WardPriorityQueueItem } from "./autoDemoTypes";
import { loadUiMode, saveUiMode } from "./autoDemoTypes";
import { buildFallbackQueue, extractQueueFromLastStep, pickLatestWardPayload, queueSignature } from "./autoDemoWardQueue";
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

function getSeverityClass(sev: string | undefined): string {
  if (sev === "critical") return "critical";
  if (sev === "unstable") return "warning";
  return "normal";
}

function careSortKey(phase: string | undefined): number {
  if (phase === "critical") return 0;
  if (phase === "unstable") return 1;
  return 2;
}

function fmtCell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function CollapsibleRaw({ title, children, defaultOpen }: { title: string; children: ReactNode; defaultOpen?: boolean }) {
  return (
    <details className="adDetails" open={defaultOpen}>
      <summary className="adDetailsSummary">{title}</summary>
      <div className="adDetailsBody">{children}</div>
    </details>
  );
}

function AgentOutputBlock({
  title,
  rows,
  presentation,
  emptyHint,
}: {
  title: string;
  rows: JsonObj[];
  presentation: boolean;
  emptyHint: string;
}) {
  const latest = rows[0] as JsonObj | undefined;
  const payload = (latest?.payload ?? {}) as JsonObj;
  if (!latest) {
    return (
      <div className="adAgentBlock">
        <h4>{title}</h4>
        <p className="adMuted">{emptyHint}</p>
      </div>
    );
  }
  const keys = Object.keys(payload).filter((k) => !["schema_version", "agent"].includes(k)).slice(0, 12);
  return (
    <div className="adAgentBlock">
      <h4>{title}</h4>
      <div className="scKeyValue">
        <span>generated_at</span>
        <strong>{fmtCell(latest.generated_at)}</strong>
      </div>
      <div className="scKeyValue">
        <span>output_type</span>
        <strong>{fmtCell(latest.output_type)}</strong>
      </div>
      {keys.map((k) => (
        <div className="adKeyLine" key={k}>
          <span className="adKey">{k}</span>
          <span className="adVal">{typeof payload[k] === "object" ? JSON.stringify(payload[k]).slice(0, 200) : fmtCell(payload[k])}</span>
        </div>
      ))}
      {!presentation && (
        <CollapsibleRaw title="Raw payload JSON">
          <pre className="adSmallPre">{JSON.stringify(payload, null, 2)}</pre>
        </CollapsibleRaw>
      )}
    </div>
  );
}

export default function AutoDemoPage() {
  const [uiMode, setUiMode] = useState<UiMode>(() => loadUiMode());
  const [state, setState] = useState<DemoState | null>(null);
  const [timeline, setTimeline] = useState<JsonObj[]>([]);
  const [lastStep, setLastStep] = useState<DemoNextFull | null>(null);
  const [admissions, setAdmissions] = useState<DemoAdmission[]>([]);
  const [boardRows, setBoardRows] = useState<AdmissionBoardRow[]>([]);
  const [wardQueue, setWardQueue] = useState<WardPriorityQueueItem[]>([]);
  const [wardQueueSource, setWardQueueSource] = useState<string>("");
  const [queueUpdatedBanner, setQueueUpdatedBanner] = useState(false);
  const prevSigRef = useRef<string>("");

  const [selectedAdmissionId, setSelectedAdmissionId] = useState<string>("");
  const [selectedPatientState, setSelectedPatientState] = useState<JsonObj | null>(null);
  const [selectedVitals, setSelectedVitals] = useState<JsonObj[]>([]);
  const [selectedInterventions, setSelectedInterventions] = useState<JsonObj[]>([]);
  const [selectedClinicalSummaries, setSelectedClinicalSummaries] = useState<JsonObj[]>([]);
  const [selectedTrackerOutputs, setSelectedTrackerOutputs] = useState<JsonObj[]>([]);
  const [selectedBedside, setSelectedBedside] = useState<JsonObj[]>([]);
  const [selectedMemory, setSelectedMemory] = useState<JsonObj[]>([]);
  const [selectedRiskOut, setSelectedRiskOut] = useState<JsonObj[]>([]);
  const [selectedRisks, setSelectedRisks] = useState<JsonObj[]>([]);
  const [selectedClinicalEvents, setSelectedClinicalEvents] = useState<JsonObj[]>([]);
  const [selectedTrackerEvents, setSelectedTrackerEvents] = useState<JsonObj[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [workingSeconds, setWorkingSeconds] = useState(0);
  const [error, setError] = useState("");

  const presentation = uiMode === "presentation";

  useEffect(() => {
    saveUiMode(uiMode);
  }, [uiMode]);

  useEffect(() => {
    if (!loading) return;
    const id = window.setInterval(() => setWorkingSeconds((s) => s + 1), 1000);
    return () => window.clearInterval(id);
  }, [loading]);

  const subEventChainTimings = useMemo(() => {
    const wr = (lastStep?.event_write_result ?? {}) as JsonObj;
    const subs = (wr.sub_events as JsonObj[] | undefined) ?? [];
    if (!Array.isArray(subs) || subs.length === 0) return [];
    return subs.map((s, i) => {
      const dr = (s.write_result as JsonObj)?.dispatch_result as JsonObj | undefined;
      const ms = dr?.total_chain_ms;
      const steps = (dr?.steps as JsonObj[] | undefined) ?? [];
      const stepBrief = steps
        .map((x) => `${String(x.step_name)} ${x.duration_ms != null ? `${x.duration_ms}ms` : "?"}`)
        .join(" → ");
      const aid = String(s.admission_id ?? "").slice(0, 14);
      return `${i + 1}. ${String(s.type)} ${aid}…  chain ${ms != null ? `${ms}ms` : "—"}  |  ${stepBrief || "(no dispatch steps)"}`;
    });
  }, [lastStep]);

  const sortedBoard = useMemo(() => {
    return [...boardRows].sort((a, b) => {
      const d = careSortKey(a.care_phase) - careSortKey(b.care_phase);
      if (d !== 0) return d;
      if (b.risk_count !== a.risk_count) return b.risk_count - a.risk_count;
      return String(b.updated_at ?? "").localeCompare(String(a.updated_at ?? ""));
    });
  }, [boardRows]);

  const activeAdmissions = useMemo(() => admissions.filter((a) => a.status === "active"), [admissions]);

  const agentOps = useMemo(() => (lastStep?.triggered_agents ?? []) as JsonObj[], [lastStep]);

  const filteredAgentOps = useMemo(() => {
    if (!selectedAgent) return agentOps;
    return agentOps.filter((a) => String(a.producer_agent ?? "") === selectedAgent);
  }, [agentOps, selectedAgent]);

  const agentNames = useMemo(
    () => Array.from(new Set(agentOps.map((a) => String(a.producer_agent ?? "")))).filter(Boolean),
    [agentOps]
  );

  const narrativeLines = useMemo(() => buildStepNarrativeLines(lastStep), [lastStep]);
  const pipelineNodes = useMemo(() => inferPipelineStatuses(lastStep), [lastStep]);

  const currentEventBedId = useMemo(() => resolveCurrentEventBedId(lastStep, admissions), [lastStep, admissions]);
  const currentEventAdmissionId = useMemo(() => String(lastStep?.admission_id ?? ""), [lastStep]);

  const selectedBedId = useMemo(() => {
    const fromState = String(selectedPatientState?.bed_id ?? "");
    if (fromState) return fromState;
    const row = admissions.find((a) => a.admission_id === selectedAdmissionId);
    return row?.bed_id ?? "";
  }, [admissions, selectedAdmissionId, selectedPatientState]);

  const mismatchSelectedVsEvent = Boolean(
    currentEventAdmissionId && selectedAdmissionId && currentEventAdmissionId !== selectedAdmissionId
  );

  const enrichBoard = useCallback(async (active: DemoAdmission[]): Promise<AdmissionBoardRow[]> => {
    if (active.length === 0) return [];
    const states = await Promise.all(active.map((a) => api.getCurrentState(a.admission_id).catch(() => null)));
    return active.map((a, i) => {
      const st = states[i] as JsonObj | null;
      const risks = Array.isArray(st?.active_risks) ? (st.active_risks as unknown[]).length : 0;
      const phase = String(st?.care_phase ?? a.severity_on_admission ?? "stable");
      return {
        admission_id: a.admission_id,
        patient_id: a.patient_id,
        bed_id: a.bed_id,
        status: a.status,
        severity_on_admission: a.severity_on_admission,
        primary_diagnosis: a.primary_diagnosis,
        admission_reason: a.admission_reason,
        admit_time: a.admit_time,
        care_phase: phase,
        risk_count: risks,
        updated_at: String(st?.updated_at ?? ""),
      };
    });
  }, []);

  const loadWardQueue = useCallback(
    async (stepForQueue: DemoNextFull | null | undefined, enriched: AdmissionBoardRow[]) => {
      let q: WardPriorityQueueItem[] = [];
      let src = "";
      const extracted = stepForQueue != null ? extractQueueFromLastStep(stepForQueue) : null;
      if (extracted?.queue.length) {
        q = extracted.queue;
        src = extracted.source;
      } else if (enriched.length > 0) {
        const wardRows = await Promise.all(
          enriched.map((r) => api.getAgentOutputs(r.admission_id, "ward_coordinator", 12).catch(() => [] as JsonObj[]))
        );
        const picked = pickLatestWardPayload(wardRows as JsonObj[][]);
        if (picked?.queue.length) {
          q = picked.queue;
          src = "ward_api";
        }
      }
      if (!q.length && enriched.length) {
        const fb = buildFallbackQueue(enriched);
        q = fb.queue;
        src = fb.source;
      }
      const sig = queueSignature(q);
      if (prevSigRef.current && sig && sig !== prevSigRef.current) setQueueUpdatedBanner(true);
      else setQueueUpdatedBanner(false);
      prevSigRef.current = sig;
      setWardQueue(q);
      setWardQueueSource(src);
    },
    []
  );

  const refreshAll = useCallback(
    async (stepForQueue?: DemoNextFull | null) => {
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
        const active = rows.filter((r) => r.status === "active");
        const enriched = await enrichBoard(active);
        setBoardRows(enriched);

        await loadWardQueue(stepForQueue, enriched);

        if (rows.length > 0) {
          setSelectedAdmissionId((prev) => {
            const still = rows.some((r) => r.admission_id === prev && r.status === "active");
            if (prev && still) return prev;
            return rows.find((r) => r.status === "active")?.admission_id ?? "";
          });
        } else {
          setSelectedAdmissionId("");
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "load failed");
      }
    },
    [enrichBoard, loadWardQueue]
  );

  async function loadAdmissionDetail(admissionId: string) {
    if (!admissionId) {
      setSelectedPatientState(null);
      setSelectedVitals([]);
      setSelectedInterventions([]);
      setSelectedClinicalSummaries([]);
      setSelectedTrackerOutputs([]);
      setSelectedBedside([]);
      setSelectedMemory([]);
      setSelectedRiskOut([]);
      setSelectedRisks([]);
      setSelectedClinicalEvents([]);
      setSelectedTrackerEvents([]);
      return;
    }
    const [
      st,
      vitals,
      interventions,
      summaries,
      tracker,
      bedside,
      memory,
      riskOut,
      risks,
      csEvents,
      itEvents,
    ] = await Promise.all([
      api.getCurrentState(admissionId).catch(() => null),
      api.getVitals(admissionId, 50).catch(() => []),
      api.getInterventions(admissionId, 50).catch(() => []),
      api.getAgentOutputs(admissionId, "clinical_summary", 20).catch(() => []),
      api.getAgentOutputs(admissionId, "intervention_tracker", 20).catch(() => []),
      api.getAgentOutputs(admissionId, "bedside_monitor", 20).catch(() => []),
      api.getAgentOutputs(admissionId, "patient_memory", 20).catch(() => []),
      api.getAgentOutputs(admissionId, "risk_sentinel", 20).catch(() => []),
      api.getRisks(admissionId, 30).catch(() => []),
      api.getAgentEvents(admissionId, "clinical_summary", 20).catch(() => []),
      api.getAgentEvents(admissionId, "intervention_tracker", 20).catch(() => []),
    ]);
    setSelectedPatientState((st as JsonObj) ?? null);
    setSelectedVitals((vitals as JsonObj[]) ?? []);
    setSelectedInterventions((interventions as JsonObj[]) ?? []);
    setSelectedClinicalSummaries((summaries as JsonObj[]) ?? []);
    setSelectedTrackerOutputs((tracker as JsonObj[]) ?? []);
    setSelectedBedside((bedside as JsonObj[]) ?? []);
    setSelectedMemory((memory as JsonObj[]) ?? []);
    setSelectedRiskOut((riskOut as JsonObj[]) ?? []);
    setSelectedRisks((risks as JsonObj[]) ?? []);
    setSelectedClinicalEvents((csEvents as JsonObj[]) ?? []);
    setSelectedTrackerEvents((itEvents as JsonObj[]) ?? []);
  }

  async function resetDemo() {
    setLoading(true);
    setWorkingSeconds(0);
    setError("");
    try {
      await api.demoAutoReset();
      setLastStep(null);
      prevSigRef.current = "";
      await refreshAll(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "reset failed");
    } finally {
      setLoading(false);
    }
  }

  async function nextStep() {
    setLoading(true);
    setWorkingSeconds(0);
    setError("");
    try {
      const out = (await api.demoAutoNext()) as unknown as DemoNextFull;
      setLastStep(out);
      setSelectedAgent("");
      await refreshAll(out);
    } catch (e) {
      setError(e instanceof Error ? e.message : "next step failed");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refreshAll(undefined);
  }, [refreshAll]);

  useEffect(() => {
    void loadAdmissionDetail(selectedAdmissionId);
  }, [selectedAdmissionId]);

  return (
    <div className="scPage">
      <header className="scTopBar">
        <div>
          <h1>Auto ICU Demo</h1>
          <p>ICU multi-agent demo dashboard — presentation vs debug</p>
        </div>
        <div className="scTopActions">
          <label className="adModeToggle">
            <span>UI mode</span>
            <select value={uiMode} onChange={(e) => setUiMode(e.target.value as UiMode)}>
              <option value="presentation">Presentation</option>
              <option value="debug">Debug</option>
            </select>
          </label>
          <a href="/">Back to Console</a>
          <button type="button" onClick={() => void resetDemo()} disabled={loading}>
            {loading ? "Working..." : "Reset Hospital"}
          </button>
          <button type="button" onClick={() => void nextStep()} disabled={loading}>
            {loading ? "Working..." : "Next Step (+5min)"}
          </button>
        </div>
      </header>

      {error && <div className="scError">{error}</div>}

      {loading && (
        <div className="adStepWaitBanner" role="status" aria-live="polite">
          <strong>处理中… 已等待 {workingSeconds}s</strong>
          <p>
            每一步是<strong>批量</strong>：每位在院患者会顺序跑一条临床事件链；链上的{" "}
            <code>patient_memory</code>、<code>risk_sentinel</code>、<code>clinical_summary</code>、
            <code>ward_coordinator</code> 等会对教学网关做<strong>同步 HTTP</strong>（大模型单次常数秒到数十秒）。整步在一个数据库事务里完成，
            浏览器在收到本接口响应前<strong>无法</strong>显示每个 Agent 的实时进度（不是前端卡死）。完成后可在 Debug 面板查看各子链{" "}
            <code>duration_ms</code> / <code>total_chain_ms</code>。
          </p>
        </div>
      )}

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
          <h2>Hospital Situation</h2>
          {sortedBoard.length === 0 && <div>No active patients in hospital.</div>}
          <div className="patientGrid">
            {sortedBoard.map((a) => (
              <button
                key={a.admission_id}
                type="button"
                className={`patientCard ${getSeverityClass(a.care_phase ?? a.severity_on_admission)} ${
                  selectedAdmissionId === a.admission_id ? "selected" : ""
                } ${currentEventAdmissionId === a.admission_id ? "patientCardEventStep" : ""}`}
                onClick={() => setSelectedAdmissionId(a.admission_id)}
              >
                <div className="patientCardTop">
                  <strong>{a.bed_id}</strong>
                  <span>{a.care_phase ?? a.severity_on_admission ?? "—"}</span>
                </div>
                {currentEventAdmissionId === a.admission_id && <div className="adStepBadge">This step</div>}
                <div>Patient: {a.patient_id}</div>
                <div>Admission: {a.admission_id}</div>
                <div className="patientCardSub">{a.primary_diagnosis ?? "N/A"}</div>
                <div className="patientCardMeta">
                  Risks: {a.risk_count} · Updated: {a.updated_at ? a.updated_at.slice(0, 19) : "—"}
                </div>
              </button>
            ))}
          </div>
        </div>

        <div className="scPanel adCurrentEventPanel">
          <h2>Current Step</h2>
          <div className="adBanner adBannerInfo">
            <strong>Current event affects:</strong> Bed <code>{currentEventBedId || "—"}</code> / Admission{" "}
            <code>{currentEventAdmissionId || "—"}</code>
          </div>
          {mismatchSelectedVsEvent && (
            <div className="adBanner adBannerWarn">
              Selected patient differs from the admission in this step — left column is long-term detail for the
              selected bed; this panel describes the latest simulation step.
            </div>
          )}
          <div className="adNarrativeCard">
            <h3>What happened</h3>
            <ul className="adNarrativeList">
              {narrativeLines.map((line, i) => (
                <li key={i}>{line}</li>
              ))}
            </ul>
          </div>

          <div className="adPipeline">
            <h3>Agent pipeline</h3>
            <div className="adPipelineTrack">
              {pipelineNodes.map((n) => (
                <div className={`adPipelineNode adPipe_${n.status}`} key={n.id}>
                  <div className="adPipelineName">{n.id.replace(/_/g, " ")}</div>
                  <div className="adPipelineStatus">{n.status}</div>
                  <div className="adPipelineHint">{n.hint}</div>
                </div>
              ))}
            </div>
          </div>

          {queueUpdatedBanner && wardQueueSource !== "fallback" && (
            <div className="adBanner adBannerOk">Queue updated after current event</div>
          )}

          <div className="adWardQueuePanel">
            <h3>Ward coordinator queue</h3>
            {wardQueueSource === "fallback" && (
              <p className="adMuted">Fallback ordering (no ward_coordinator snapshot in DB for this refresh).</p>
            )}
            {wardQueue.length === 0 && <p className="adMuted">No active patients to rank.</p>}
            <table className="scTable adQueueTable">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Bed</th>
                  <th>Admission</th>
                  <th>Phase</th>
                  <th>Score</th>
                  <th>Level</th>
                  <th>Next attention</th>
                </tr>
              </thead>
              <tbody>
                {wardQueue.map((q) => (
                  <tr
                    key={`${q.rank}-${q.admission_id}`}
                    className={q.admission_id === currentEventAdmissionId ? "rowActive" : ""}
                    onClick={() => q.admission_id && setSelectedAdmissionId(q.admission_id)}
                  >
                    <td>{q.rank ?? "—"}</td>
                    <td>{fmtCell(q.bed_id)}</td>
                    <td>
                      <code>{fmtCell(q.admission_id)}</code>
                    </td>
                    <td>{fmtCell(q.care_phase)}</td>
                    <td>{fmtCell(q.priority_score)}</td>
                    <td>{fmtCell(q.priority_level)}</td>
                    <td>{fmtCell(q.suggested_attention ?? q.summary_hint)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {wardQueue.map((q, qi) => (
              <CollapsibleRaw key={`ex-${q.admission_id}-${qi}`} title={`Factors: ${q.bed_id}`}>
                <pre className="adSmallPre">{JSON.stringify(q.reason ?? q, null, 2)}</pre>
              </CollapsibleRaw>
            ))}
          </div>

          {!presentation && subEventChainTimings.length > 0 && (
            <CollapsibleRaw title="Sub-event orchestrator timings (duration_ms per agent)" defaultOpen>
              <pre className="adSubEventTiming">{subEventChainTimings.join("\n")}</pre>
            </CollapsibleRaw>
          )}

          {!presentation && (
            <CollapsibleRaw title="Raw: last step JSON (debug)" defaultOpen={false}>
              <pre className="adSmallPre">{JSON.stringify(lastStep ?? {}, null, 2)}</pre>
            </CollapsibleRaw>
          )}
        </div>
      </section>

      <section className="scGrid2">
        <div className="scPanel">
          <h2>Selected patient detail</h2>
          <div className="adBanner adBannerInfo">
            <strong>Selected:</strong> Bed <code>{selectedBedId || "—"}</code> / Admission <code>{selectedAdmissionId || "—"}</code>
          </div>
          {!selectedAdmissionId && <div>Select a patient card or a queue row.</div>}
          {selectedAdmissionId && (
            <>
              <div className="scKeyValue">
                <span>Care phase</span>
                <strong>{String(selectedPatientState?.care_phase ?? "unknown")}</strong>
              </div>
              <div className="scKeyValue">
                <span>Active risks (state)</span>
                <strong>{Array.isArray(selectedPatientState?.active_risks) ? selectedPatientState?.active_risks.length : 0}</strong>
              </div>
              <div className="scDivider" />

              <h3>Recent vitals</h3>
              {selectedVitals.length === 0 ? (
                <p className="adMuted">No vital rows yet.</p>
              ) : (
                <div className="scScrollBox">
                  <table className="scTable">
                    <thead>
                      <tr>
                        <th>Time</th>
                        <th>HR</th>
                        <th>MAP</th>
                        <th>SBP</th>
                        <th>DBP</th>
                        <th>RR</th>
                        <th>SpO₂</th>
                        <th>Temp</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedVitals.slice(0, 20).map((v) => (
                        <tr key={String(v.id ?? v.timestamp)}>
                          <td>{fmtCell(v.timestamp)}</td>
                          <td>{fmtCell(v.heart_rate)}</td>
                          <td>{fmtCell(v.mean_arterial_pressure)}</td>
                          <td>{fmtCell(v.systolic_bp)}</td>
                          <td>{fmtCell(v.diastolic_bp)}</td>
                          <td>{fmtCell(v.respiratory_rate)}</td>
                          <td>{fmtCell(v.spo2)}</td>
                          <td>{fmtCell(v.temperature)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <h3>Recent interventions</h3>
              {selectedInterventions.length === 0 ? (
                <p className="adMuted">No interventions yet.</p>
              ) : (
                <ul className="adList">
                  {selectedInterventions.slice(0, 10).map((x) => (
                    <li key={String(x.event_id ?? x.detail_id)}>
                      <strong>{String(x.timestamp ?? "").slice(0, 19)}</strong> — {String(x.intervention_type)}: {String(x.description ?? "").slice(0, 120)}
                    </li>
                  ))}
                </ul>
              )}

              <AgentOutputBlock
                title="Latest bedside monitor output"
                rows={selectedBedside}
                presentation={presentation}
                emptyHint="No bedside_monitor output yet."
              />
              <AgentOutputBlock
                title="Latest intervention tracker output"
                rows={selectedTrackerOutputs}
                presentation={presentation}
                emptyHint="No intervention_tracker output yet (needs intervention + follow-up data)."
              />
              <AgentOutputBlock
                title="Latest patient memory output"
                rows={selectedMemory}
                presentation={presentation}
                emptyHint="No patient_memory output yet."
              />
              <div className="adAgentBlock">
                <h4>Latest risk sentinel</h4>
                {selectedRisks.length === 0 ? (
                  <p className="adMuted">No risk_assessments rows.</p>
                ) : (
                  <ul className="adList">
                    {selectedRisks.slice(0, 8).map((r) => (
                      <li key={String(r.id ?? r.timestamp)}>
                        {String(r.timestamp ?? "").slice(0, 19)} — {String(r.risk_type)} ({String(r.severity)})
                      </li>
                    ))}
                  </ul>
                )}
                {selectedRiskOut.length > 0 ? (
                  <AgentOutputBlock
                    title="Risk sentinel agent output"
                    rows={selectedRiskOut}
                    presentation={presentation}
                    emptyHint="No risk_sentinel agent output."
                  />
                ) : (
                  <p className="adMuted">No risk_sentinel agent_outputs row yet.</p>
                )}
              </div>
              <AgentOutputBlock
                title="Latest clinical summary output"
                rows={selectedClinicalSummaries}
                presentation={presentation}
                emptyHint="No clinical_summary yet."
              />
              {!presentation && selectedClinicalSummaries.length === 0 && (
                <CollapsibleRaw title="clinical_summary events (debug)">
                  <pre className="adSmallPre">{JSON.stringify(selectedClinicalEvents.slice(0, 5), null, 2)}</pre>
                </CollapsibleRaw>
              )}
              {!presentation && (
                <CollapsibleRaw title="intervention_tracker events (debug)">
                  <pre className="adSmallPre">{JSON.stringify(selectedTrackerEvents.slice(0, 5), null, 2)}</pre>
                </CollapsibleRaw>
              )}
            </>
          )}
        </div>

        <div className="scPanel">
          <h2>Timeline</h2>
          <p className="adMuted">Latest simulation steps. Expand a row for raw JSON.</p>
          <div className="adTimelineList">
            {timeline.slice(0, 25).map((row) => (
              <div className="adTimelineRow" key={String(row.id ?? row.step_index)}>
                <div className="adTimelineHead">
                  <span className="adTIdx">#{String(row.step_index)}</span>
                  <span className="adTTime">{String(row.sim_time ?? "").slice(0, 19)}</span>
                  <span className="adTType">{String(row.event_type)}</span>
                  <code className="adTAdm">{String(row.admission_id ?? "—")}</code>
                </div>
                <div className="adTLine">{timelineOneLine(row)}</div>
                {!presentation && (
                  <details className="adDetails">
                    <summary className="adDetailsSummary">Raw payload / result</summary>
                    <div className="adDetailsBody">
                      <strong>payload</strong>
                      <pre className="adSmallPre">{JSON.stringify(row.payload ?? {}, null, 2)}</pre>
                      <strong>result</strong>
                      <pre className="adSmallPre">{JSON.stringify(row.result ?? {}, null, 2)}</pre>
                    </div>
                  </details>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="scPanel">
        <h2>Agent reactions (this step)</h2>
        <div className="scTopActions" style={{ marginBottom: 10 }}>
          <span>Filter agent:</span>
          <select value={selectedAgent} onChange={(e) => setSelectedAgent(e.target.value)}>
            <option value="">All</option>
            {agentNames.map((name) => (
              <option value={name} key={name}>
                {name}
              </option>
            ))}
          </select>
        </div>
        <div className="scKeyValue">
          <span>Triggered agents</span>
          <strong>{(lastStep?.agent_delta_summary as JsonObj)?.triggered_agent_names ? JSON.stringify((lastStep?.agent_delta_summary as JsonObj).triggered_agent_names) : "—"}</strong>
        </div>
        <div className="scKeyValue">
          <span>DB effects</span>
          <strong>{lastStep?.db_effects ? JSON.stringify(lastStep.db_effects) : "—"}</strong>
        </div>
        <div className="scDivider" />
        {filteredAgentOps.length === 0 && <div>No agent operations for this step.</div>}
        {filteredAgentOps.map((op, idx) => (
          <div className="reactionItem adReactionCard" key={`${String(op.producer_agent ?? "agent")}_${idx}`}>
            <div className="reactionHeader">
              <strong>{String(op.producer_agent ?? "")}</strong>
              <span>{String(op.event_type ?? "")}</span>
              <span>{String(op.produced_at ?? "")}</span>
            </div>
            <p className="adReactionSummary">{reactionSummary(op)}</p>
            <ul className="adList">
              {reactionEvidence(op).map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
            {!presentation && (
              <CollapsibleRaw title="Raw payload">
                <pre className="adSmallPre">{JSON.stringify(op.payload ?? {}, null, 2)}</pre>
              </CollapsibleRaw>
            )}
          </div>
        ))}
      </section>

      {presentation && lastStep && (
        <section className="scPanel adHintFooter">
          <p className="adMuted">Switch to <strong>Debug</strong> mode to inspect full JSON, timeline payloads, and LLM audit fields.</p>
        </section>
      )}
    </div>
  );
}
