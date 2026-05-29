import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../api";
import type { JsonObj } from "../types";
import { buildFixedBedSlots } from "./autoDemoBeds";
import { DEMO_MAX_BEDS, DEMO_MIN_ACTIVE_PATIENTS } from "./autoDemoConstants";
import { buildLlmTraceRows } from "./autoDemoLlmTrace";
import { buildStepNarrativeLines, resolveCurrentEventBedId } from "./autoDemoNarrative";
import { inferPipelineStatuses } from "./autoDemoPipeline";
import { bedIdsInStepEvents, buildStepEventItems } from "./autoDemoStepEvents";
import { reactionEvidence, reactionSummary, timelineOneLine } from "./autoDemoReactionHelpers";
import type { AdmissionBoardRow, DemoNextFull, UiMode, WardPriorityQueueItem } from "./autoDemoTypes";
import { loadUiMode, saveUiMode } from "./autoDemoTypes";
import { buildFallbackQueue, extractQueueFromLastStep, pickLatestWardPayload, queueSignature } from "./autoDemoWardQueue";
import { formatProgressLine, progressKind, type DemoProgressEvent } from "./autoDemoProgress";
import { buildTimelineSteps, formatSimTimeLabel, resolveViewPosition } from "./autoDemoTimelineNav";
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
  const [progressLines, setProgressLines] = useState<DemoProgressEvent[]>([]);
  const [plannedSimAfter, setPlannedSimAfter] = useState<string | null>(null);
  const [viewingStepIndex, setViewingStepIndex] = useState<number | null>(null);
  const progressEndRef = useRef<HTMLLIElement>(null);
  const [error, setError] = useState("");
  const [mdtLoading, setMdtLoading] = useState(false);
  const [mdtError, setMdtError] = useState("");
  const [mdtResult, setMdtResult] = useState<JsonObj | null>(null);
  const [familyDraftLoading, setFamilyDraftLoading] = useState(false);
  const [familyDraftError, setFamilyDraftError] = useState("");
  const [familyDraft, setFamilyDraft] = useState<JsonObj | null>(null);
  const [patientActionLoading, setPatientActionLoading] = useState(false);
  const [patientActionError, setPatientActionError] = useState("");

  const presentation = uiMode === "presentation";

  useEffect(() => {
    saveUiMode(uiMode);
  }, [uiMode]);

  useEffect(() => {
    if (!loading) return;
    const id = window.setInterval(() => setWorkingSeconds((s) => s + 1), 1000);
    return () => window.clearInterval(id);
  }, [loading]);

  useEffect(() => {
    if (!loading) return;
    progressEndRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [progressLines.length, loading]);

  const timelineSteps = useMemo(() => buildTimelineSteps(timeline), [timeline]);

  const viewPosition = useMemo(
    () => resolveViewPosition(timelineSteps, viewingStepIndex, state?.step_index ?? null),
    [timelineSteps, viewingStepIndex, state?.step_index]
  );

  const displayedStep = useMemo((): DemoNextFull | null => {
    if (viewingStepIndex != null) {
      const hit = timelineSteps.find((s) => s.step_index === viewingStepIndex);
      if (hit?.step) return hit.step;
    }
    return lastStep;
  }, [viewingStepIndex, lastStep, timelineSteps]);

  const isViewingHistory = Boolean(
    displayedStep && viewPosition.step_index != null && !viewPosition.isLatest && (state?.step_index ?? 0) > (viewPosition.step_index ?? 0)
  );

  const canGoPrevStep = viewPosition.listIndex > 0;
  const canGoNextStep = viewPosition.listIndex >= 0 && viewPosition.listIndex < timelineSteps.length - 1;

  const statusBarTitle = useMemo(() => {
    if (loading) {
      const sim = plannedSimAfter ? formatSimTimeLabel(plannedSimAfter) : "";
      return `本步进行中… 已等待 ${workingSeconds}s${sim ? ` · 下一步仿真时间：${sim}` : ""}`;
    }
    if (lastStep || (state?.step_index ?? 0) > 0) {
      const sim = formatSimTimeLabel(lastStep?.sim_time_after ?? state?.sim_time);
      const step = state?.step_index ?? lastStep?.step_index ?? "—";
      return `本步骤结束 · Step #${step}${sim ? ` · 仿真时间：${sim}` : ""}`;
    }
    return "等待点击 Next Step 开始演示";
  }, [loading, workingSeconds, plannedSimAfter, lastStep, state?.sim_time, state?.step_index]);

  const progressToasts = useMemo(() => {
    if (!loading) return [];
    return progressLines
      .filter((ev) =>
        [
          "patient_clinical_start",
          "patient_clinical_done",
          "agent_request_fulfilled",
          "agent_start",
          "agent_done",
          "knowledge_done",
          "llm_end",
          "ward_batch_done",
        ].includes(ev.type)
      )
      .slice(-4)
      .reverse();
  }, [loading, progressLines]);

  const subEventChainTimings = useMemo(() => {
    const wr = (displayedStep?.event_write_result ?? {}) as JsonObj;
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
  }, [displayedStep]);

  const fixedBedSlots = useMemo(() => buildFixedBedSlots(boardRows), [boardRows]);

  const activeAdmissions = useMemo(() => admissions.filter((a) => a.status === "active"), [admissions]);
  const selectedIsActive = useMemo(
    () => activeAdmissions.some((a) => a.admission_id === selectedAdmissionId),
    [activeAdmissions, selectedAdmissionId]
  );

  const stepEventItems = useMemo(
    () => buildStepEventItems(displayedStep as JsonObj | null, admissions),
    [displayedStep, admissions]
  );

  const stepHighlightBeds = useMemo(() => bedIdsInStepEvents(stepEventItems), [stepEventItems]);

  const llmTraceRows = useMemo(
    () => buildLlmTraceRows(displayedStep?.agent_workflow_trace),
    [displayedStep?.agent_workflow_trace]
  );

  const agentOps = useMemo(() => (displayedStep?.triggered_agents ?? []) as JsonObj[], [displayedStep]);

  const wardNarrative = useMemo(() => {
    const trace = displayedStep?.agent_workflow_trace ?? [];
    const ward = trace.find((t) => String(t.agent_name ?? "") === "ward_coordinator");
    return (ward?.judgment as JsonObj | undefined) ?? null;
  }, [displayedStep?.agent_workflow_trace]);

  const filteredAgentOps = useMemo(() => {
    if (!selectedAgent) return agentOps;
    return agentOps.filter((a) => String(a.producer_agent ?? "") === selectedAgent);
  }, [agentOps, selectedAgent]);

  const agentNames = useMemo(
    () => Array.from(new Set(agentOps.map((a) => String(a.producer_agent ?? "")))).filter(Boolean),
    [agentOps]
  );

  const narrativeLines = useMemo(() => buildStepNarrativeLines(displayedStep), [displayedStep]);
  const pipelineNodes = useMemo(() => inferPipelineStatuses(displayedStep), [displayedStep]);

  const currentEventBedId = useMemo(() => resolveCurrentEventBedId(displayedStep, admissions), [displayedStep, admissions]);
  const currentEventAdmissionId = useMemo(() => String(displayedStep?.admission_id ?? ""), [displayedStep]);

  const goToPrevTimelineStep = useCallback(() => {
    if (viewPosition.listIndex > 0) {
      setViewingStepIndex(timelineSteps[viewPosition.listIndex - 1].step_index);
    }
  }, [timelineSteps, viewPosition.listIndex]);

  const goToNextTimelineStep = useCallback(() => {
    if (viewPosition.listIndex >= 0 && viewPosition.listIndex < timelineSteps.length - 1) {
      setViewingStepIndex(timelineSteps[viewPosition.listIndex + 1].step_index);
    }
  }, [timelineSteps, viewPosition.listIndex]);

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
      setFamilyDraft(null);
      setFamilyDraftError("");
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
    setFamilyDraft(null);
    setFamilyDraftError("");
  }

  async function generateFamilyDraft() {
    if (!selectedAdmissionId) return;
    setFamilyDraftLoading(true);
    setFamilyDraftError("");
    try {
      const res = await api.generateFamilyDraft(selectedAdmissionId);
      setFamilyDraft(res);
      const drafts = await api.getAgentOutputs(selectedAdmissionId, "compassion_family_communication", 5).catch(() => []);
      if (drafts.length > 0) setSelectedAgent("compassion_family_communication");
    } catch (e) {
      setFamilyDraft(null);
      setFamilyDraftError(e instanceof Error ? e.message : "生成家属沟通稿失败");
    } finally {
      setFamilyDraftLoading(false);
    }
  }

  async function resetDemo() {
    setLoading(true);
    setWorkingSeconds(0);
    setError("");
    setPatientActionError("");
    try {
      await api.demoAutoReset();
      setLastStep(null);
      setViewingStepIndex(null);
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
    setProgressLines([]);
    setPlannedSimAfter(null);
    setError("");
    setPatientActionError("");
    try {
      const out = (await api.demoAutoNextStream((ev) => {
        const row = ev as DemoProgressEvent;
        if (row.type === "step_plan" && row.sim_after) {
          setPlannedSimAfter(String(row.sim_after));
        }
        setProgressLines((prev) => [...prev, row]);
      })) as unknown as DemoNextFull;
      setLastStep(out);
      setViewingStepIndex(null);
      setSelectedAgent("");
      await refreshAll(out);
    } catch (e) {
      setError(e instanceof Error ? e.message : "next step failed");
    } finally {
      setLoading(false);
    }
  }

  async function addRandomPatient() {
    setPatientActionLoading(true);
    setPatientActionError("");
    try {
      const res = await api.demoAutoAddPatient();
      const admission = (res.admission ?? {}) as JsonObj;
      const admissionId = String(admission.admission_id ?? "");
      await refreshAll(lastStep);
      if (admissionId) setSelectedAdmissionId(admissionId);
    } catch (e) {
      setPatientActionError(e instanceof Error ? e.message : "add patient failed");
    } finally {
      setPatientActionLoading(false);
    }
  }

  async function removeSelectedPatient() {
    if (!selectedAdmissionId) return;
    setPatientActionLoading(true);
    setPatientActionError("");
    try {
      await api.demoAutoDischargePatient(selectedAdmissionId);
      setSelectedAdmissionId("");
      await refreshAll(lastStep);
    } catch (e) {
      setPatientActionError(e instanceof Error ? e.message : "remove patient failed");
    } finally {
      setPatientActionLoading(false);
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
          <h1>ICU Auto Demo Dashboard</h1>
          <p>一屏看清当前病区、正在发生的事件、患者风险与 Agent 响应</p>
        </div>
        <div className="scTopActions">
          <label className="adModeToggle">
            <span>UI mode</span>
            <select value={uiMode} onChange={(e) => setUiMode(e.target.value as UiMode)}>
              <option value="presentation">Presentation</option>
              <option value="debug">Debug</option>
            </select>
          </label>
          <button type="button" onClick={() => void resetDemo()} disabled={loading}>
            {loading ? "Working..." : "Reset Hospital"}
          </button>
          <button
            type="button"
            onClick={() => void addRandomPatient()}
            disabled={loading || patientActionLoading || (state?.active_admissions ?? 0) >= DEMO_MAX_BEDS}
            title={(state?.active_admissions ?? 0) >= DEMO_MAX_BEDS ? "ICU 床位已满" : "随机新增一位演示患者"}
          >
            {patientActionLoading ? "Working..." : "Add Patient"}
          </button>
          <button type="button" onClick={() => void nextStep()} disabled={loading}>
            {loading ? "Working..." : "Next Step (+5min)"}
          </button>
        </div>
      </header>

      {error && <div className="scError">{error}</div>}
      {patientActionError && <div className="scError">{patientActionError}</div>}

      {progressToasts.length > 0 && (
        <div className="adProgressToasts" aria-live="polite">
          {progressToasts.map((ev, i) => (
            <div key={`${ev.ts ?? ""}-${ev.type}-${i}`} className={`adProgressToast adToast-${progressKind(ev)}`}>
              <span className="adProgressPulse" />
              <strong>{ev.type === "patient_clinical_done" ? "完成" : ev.type === "patient_clinical_start" ? "进行中" : "更新"}</strong>
              <span>{formatProgressLine(ev).replace(/^\[[^\]]+\]\s*/, "")}</span>
            </div>
          ))}
        </div>
      )}

      {!loading && (state?.active_admissions ?? 0) === 0 && (
        <div className="adStepWaitBanner" role="status">
          <strong>病区暂无在院演示患者</strong>
          <p>
            点击 <strong>Next Step</strong> 会自动收治；若步数增加但面板仍为空，请先点{" "}
            <strong>Reset Hospital</strong> 再逐步推进。
          </p>
        </div>
      )}

      <div className="adStepStatusBar adLiveProgress" role="status" aria-live="polite">
        <strong>{statusBarTitle}</strong>
        {(loading || !presentation) && <div className="adLiveFeed">
          {loading && progressLines.length === 0 ? (
            <p className="adMuted">正在连接进度流…</p>
          ) : progressLines.length === 0 ? (
            <p className="adMuted">点击 Next Step 后显示本步执行进度。</p>
          ) : (
            <ul className="adLiveFeedList">
              {(presentation ? progressLines.slice(-6) : progressLines).map((ev, i) => (
                <li key={`${ev.ts ?? ""}-${ev.type}-${i}`} className={`adLiveLine adLive-${progressKind(ev)}`}>
                  {formatProgressLine(ev)}
                </li>
              ))}
              <li ref={progressEndRef} />
            </ul>
          )}
        </div>}
      </div>

      <section className="scMetrics">
        <div className="scMetricCard">
          <div className="scMetricTitle">仿真时间</div>
          <div className="scMetricValue">{state?.sim_time ?? "N/A"}</div>
        </div>
        <div className="scMetricCard">
          <div className="scMetricTitle">当前步骤</div>
          <div className="scMetricValue">{state?.step_index ?? 0}</div>
        </div>
        <div className="scMetricCard">
          <div className="scMetricTitle">在院患者</div>
          <div className="scMetricValue">{state?.active_admissions ?? 0}</div>
        </div>
        <div className="scMetricCard">
          <div className="scMetricTitle">占用床位</div>
          <div className="scMetricValue">{state?.occupied_beds ?? 0}</div>
        </div>
      </section>

      <section className="adMainSplit">
        <div className="scPanel adBedPanel">
          <h2>病区床位</h2>
          <p className="adMuted">点击床位查看患者。高亮表示本步事件涉及该床。</p>
          <div className="adBedGridFixed">
            {fixedBedSlots.map((slot) => {
              if (!slot.occupied || !slot.row) {
                return (
                  <div
                    key={slot.bed_id}
                    className={`bedCard empty ${stepHighlightBeds.has(slot.bed_id) ? "stepHighlight" : ""}`}
                  >
                    <div className="bedCardTop">
                      <span className="bedCardLabel">{slot.bed_id}</span>
                      <span>空床</span>
                    </div>
                    <div className="bedCardEmptyText">暂无患者</div>
                  </div>
                );
              }
              const a = slot.row;
              return (
                <button
                  key={slot.bed_id}
                  type="button"
                  className={`bedCard occupied patientCard ${getSeverityClass(a.care_phase ?? a.severity_on_admission)} ${
                    selectedAdmissionId === a.admission_id ? "selected" : ""
                  } ${stepHighlightBeds.has(slot.bed_id) ? "stepHighlight" : ""}`}
                  onClick={() => setSelectedAdmissionId(a.admission_id)}
                >
                  <div className="bedCardTop">
                    <span className="bedCardLabel">{slot.bed_id}</span>
                    <span>{a.care_phase ?? a.severity_on_admission ?? "—"}</span>
                  </div>
                  {currentEventAdmissionId === a.admission_id && <div className="adStepBadge">本步锚点</div>}
                  <div>患者：{a.patient_id}</div>
                  <div>入院：{a.admission_id}</div>
                  <div className="patientCardSub">{a.primary_diagnosis ?? "—"}</div>
                  <div className="patientCardMeta">
                    风险数 {a.risk_count} · 更新 {a.updated_at ? a.updated_at.slice(0, 19) : "—"}
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        <div className="scPanel adStepFeedPanel adCurrentEventPanel">
          <div className="adStepEventsHead">
            <h2 className="adStepEventsTitle">
              <button
                type="button"
                className="adStepNavBtn"
                aria-label="上一步事件"
                disabled={!canGoPrevStep}
                onClick={() => goToPrevTimelineStep()}
              >
                ←
              </button>
              <span>
                本步事件
                {viewPosition.step_index != null ? ` (Step #${viewPosition.step_index})` : ""}
                {isViewingHistory ? " · 历史" : ""}
              </span>
              <button
                type="button"
                className="adStepNavBtn"
                aria-label="下一步事件"
                disabled={!canGoNextStep}
                onClick={() => goToNextTimelineStep()}
              >
                →
              </button>
            </h2>
            {timelineSteps.length > 1 && (
              <span className="adStepNavHint">
                {viewPosition.listIndex + 1} / {timelineSteps.length}
              </span>
            )}
          </div>
          <div className="adNarrativeCard adNarrativeHero">
            <h3>本步摘要</h3>
            <ul className="adNarrativeList">
              {narrativeLines.length === 0 ? <li>等待下一步事件。</li> : narrativeLines.map((line, i) => (
                <li key={i}>{line}</li>
              ))}
            </ul>
          </div>
          {!displayedStep && <p className="adMuted">点击 Next Step 后，此处会列出本步全部子事件（收治/出院/体征/检验/干预）。</p>}
          {displayedStep && stepEventItems.length === 0 && <p className="adMuted">本步无子事件记录。</p>}
          <div className="adStepEventList">
            {stepEventItems.map((ev) => {
              const isAgentRequest = ev.type.startsWith("agent_request_");
              return (
              <div
                key={`${ev.index}-${ev.type}-${ev.admission_id}`}
                className={`adStepEventCard ${ev.tone} ${isAgentRequest ? "agentRequest" : ""}`}
                role="button"
                tabIndex={0}
                onClick={() => ev.admission_id && setSelectedAdmissionId(ev.admission_id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && ev.admission_id) setSelectedAdmissionId(ev.admission_id);
                }}
              >
                <div className="adStepEventHead">
                  <span className="adStepEventIdx">#{ev.index}</span>
                  <span className="adStepEventTitle">{ev.title}</span>
                  <span className="adStepEventMeta">
                    床 <code>{ev.bed_id}</code> · 入院 <code>{ev.admission_id.slice(0, 18)}</code>
                  </span>
                </div>
                <ul className="adStepEventDetails">
                  {ev.details.map((line, li) => (
                    <li
                      key={li}
                      className={
                        line.startsWith("请求：")
                          ? "requestLine"
                          : line.startsWith("理由：")
                          ? "reasonLine"
                          : ""
                      }
                    >
                      {line}
                    </li>
                  ))}
                </ul>
              </div>
            );
            })}
          </div>

          {!presentation && <div className="adLlmSection">
            <h3>LLM 调用（本步）</h3>
            <p className="adMuted">
              逐步对照：患者 / 床位 / Agent / 成功或 fallback / 返回摘要。完整 JSON 见 Debug 模式。
            </p>
            {(displayedStep?.agent_delta_summary as JsonObj)?.llm_used_by != null && (
              <div className="adBanner adBannerInfo" style={{ marginBottom: 8 }}>
                本步 LLM 成功标记：{JSON.stringify((displayedStep?.agent_delta_summary as JsonObj).llm_used_by)} · fallback：{" "}
                {JSON.stringify((displayedStep?.agent_delta_summary as JsonObj).fallback_used_by ?? [])}
              </div>
            )}
            {llmTraceRows.length === 0 && <p className="adMuted">本步尚无 agent_workflow_trace（或未跑 Agent）。</p>}
            {llmTraceRows.map((row, i) => (
              <div
                key={`${row.agent_name}-${row.admission_id}-${i}`}
                className={`adLlmCard ${row.status}`}
                role="button"
                tabIndex={0}
                onClick={() => {
                  if (row.admission_id && row.admission_id !== "—" && !row.admission_id.startsWith("（")) {
                    setSelectedAdmissionId(row.admission_id);
                  }
                }}
              >
                <div className="adLlmCardHead">
                  <strong>{row.agent_name}</strong>
                  <span
                    className={`adLlmBadge ${row.status === "success" ? "ok" : row.status === "fallback" ? "fail" : "skip"}`}
                  >
                    {row.status_label}
                  </span>
                  <span>
                    床 <code>{row.bed_id}</code>
                  </span>
                  <span>
                    患者 <code>{row.patient_id}</code>
                  </span>
                </div>
                <div className="scKeyValue">
                  <span>audit_log_id</span>
                  <strong>{row.audit_log_id}</strong>
                </div>
                <pre className="adLlmPreview">{row.response_preview}</pre>
              </div>
            ))}
          </div>}

          {!presentation && <div className="adBanner adBannerInfo">
            <strong>本步锚点入院：</strong> <code>{currentEventAdmissionId || "—"}</code> / 床{" "}
            <code>{currentEventBedId || "—"}</code>
          </div>}
          {!presentation && mismatchSelectedVsEvent && (
            <div className="adBanner adBannerWarn">
              左侧选中床位与锚点入院不一致；右侧为本步全部事件与 LLM 记录。
            </div>
          )}

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
            <h3>病区优先队列</h3>
            {wardQueueSource === "fallback" && (
              <p className="adMuted">Fallback ordering (no ward_coordinator snapshot in DB for this refresh).</p>
            )}
            {wardNarrative && (
              <div className="adNarrativeCard">
                <h3>Ward coordinator 总结</h3>
                {wardNarrative.ward_overview && <p>{String(wardNarrative.ward_overview)}</p>}
                {wardNarrative.priority_reasoning && <p>{String(wardNarrative.priority_reasoning)}</p>}
                {Array.isArray(wardNarrative.references_used) && wardNarrative.references_used.length > 0 && (
                  <p className="adMuted">参考：{(wardNarrative.references_used as unknown[]).slice(0, 5).map(String).join("；")}</p>
                )}
                {Array.isArray(wardNarrative.next_step_plan) && wardNarrative.next_step_plan.length > 0 && (
                  <ul className="adList">
                    {(wardNarrative.next_step_plan as unknown[]).slice(0, 5).map((x, i) => (
                      <li key={`plan-${i}`}>{String(x)}</li>
                    ))}
                  </ul>
                )}
                {Array.isArray(wardNarrative.focus_points) && wardNarrative.focus_points.length > 0 && (
                  <ul className="adList">
                    {(wardNarrative.focus_points as unknown[]).slice(0, 5).map((x, i) => (
                      <li key={`focus-${i}`}>{String(x)}</li>
                    ))}
                  </ul>
                )}
              </div>
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
                  <th>排序理由</th>
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
                    <td>
                      <div className="adQueueReasonCell">
                        {(Array.isArray(q.reason) ? q.reason : []).slice(0, 3).map((reason, i) => (
                          <span className="adQueueReasonPill" key={`${q.admission_id}-reason-${i}`}>
                            {String(reason)}
                          </span>
                        ))}
                        {q.rationale && <span className="adQueueReasonText">{String(q.rationale).slice(0, 180)}</span>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!presentation && wardQueue.map((q, qi) => (
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
              <pre className="adSmallPre">{JSON.stringify(displayedStep ?? {}, null, 2)}</pre>
            </CollapsibleRaw>
          )}
        </div>
      </section>

      <section className={`scGrid2 ${presentation ? "adPatientOnlyGrid" : ""}`}>
        <div className="scPanel">
          <h2>选中患者</h2>
          <div className="adBanner adBannerInfo">
            <strong>Selected:</strong> Bed <code>{selectedBedId || "—"}</code> / Admission <code>{selectedAdmissionId || "—"}</code>
          </div>
          {selectedAdmissionId && (
            <div className="adMdtActions">
              <button
                type="button"
                className="scBtn scBtnPrimary"
                disabled={mdtLoading || !selectedIsActive}
                onClick={async () => {
                  setMdtLoading(true);
                  setMdtError("");
                  try {
                    const res = await api.requestMdtConsultation(selectedAdmissionId, {
                      reason: "ICU manual MDT consultation",
                      use_api: false,
                    });
                    setMdtResult(res);
                    const outputs = await api.getAgentOutputs(selectedAdmissionId, "mdt_consultation", 5).catch(() => []);
                    if (outputs.length > 0) {
                      setSelectedAgent("mdt_consultation");
                    }
                  } catch (e) {
                    setMdtResult(null);
                    const msg = e instanceof Error ? e.message : String(e);
                    setMdtError(
                      msg.includes("SIMI") || msg.includes("503")
                        ? `${msg} — 请确认 simi 已启动：uvicorn mdt_consultation_api:app --port 8001`
                        : msg
                    );
                  } finally {
                    setMdtLoading(false);
                  }
                }}
              >
                {mdtLoading ? "MDT 会诊中…" : "申请 MDT 会诊"}
              </button>
              <button
                type="button"
                className="scBtn"
                disabled={!selectedAdmissionId || !selectedIsActive || familyDraftLoading}
                title={selectedAdmissionId ? "生成中文家属沟通草稿，需医生审核后使用" : "请先选择患者"}
                onClick={() => void generateFamilyDraft()}
              >
                {familyDraftLoading ? "生成中…" : "生成家属沟通稿"}
              </button>
              <button
                type="button"
                className="scBtn scBtnDanger"
                disabled={
                  !selectedAdmissionId ||
                  !selectedIsActive ||
                  loading ||
                  patientActionLoading ||
                  (state?.active_admissions ?? 0) <= DEMO_MIN_ACTIVE_PATIENTS
                }
                title={
                  (state?.active_admissions ?? 0) <= DEMO_MIN_ACTIVE_PATIENTS
                    ? `至少保留 ${DEMO_MIN_ACTIVE_PATIENTS} 位 ICU 患者`
                    : "手动将选中患者移出 ICU"
                }
                onClick={() => void removeSelectedPatient()}
              >
                {patientActionLoading ? "移出中…" : "Remove Patient"}
              </button>
            </div>
          )}
          {mdtError && <div className="adBanner adBannerWarn">{mdtError}</div>}
          {familyDraftError && <div className="adBanner adBannerWarn">{familyDraftError}</div>}
          {familyDraft && (
            <div className="adAgentBlock">
              <h4>家属沟通稿（需医生审核）</h4>
              <div className="adBanner adBannerInfo">
                这是一份给医生审核后再向家属沟通的中文草稿，不应直接发送或作为治疗承诺。
              </div>
              <p>{String(familyDraft.family_plain_language_draft ?? "")}</p>
              {familyDraft.icu_diary_draft && (
                <>
                  <h4>ICU 日记草稿</h4>
                  <p>{String(familyDraft.icu_diary_draft)}</p>
                </>
              )}
              {Array.isArray(familyDraft.communication_cautions) && familyDraft.communication_cautions.length > 0 && (
                <ul className="adList">
                  {(familyDraft.communication_cautions as unknown[]).slice(0, 5).map((x, i) => (
                    <li key={i}>{String(x)}</li>
                  ))}
                </ul>
              )}
              {!presentation && <pre className="adSmallPre">{JSON.stringify(familyDraft, null, 2)}</pre>}
            </div>
          )}
          {mdtResult && (
            <CollapsibleRaw title="MDT consultation result" defaultOpen={!presentation}>
              <div className="scKeyValue">
                <span>Status</span>
                <strong>{String((mdtResult.mdt_judgment as JsonObj)?.status_level ?? "—")}</strong>
              </div>
              <div className="scKeyValue">
                <span>Surgery ready</span>
                <strong>{String((mdtResult.mdt_judgment as JsonObj)?.surgery_ready ?? "—")}</strong>
              </div>
              <p className="adMuted">{String(mdtResult.case_summary ?? "").slice(0, 400)}</p>
              {Array.isArray(mdtResult.required_updates) && mdtResult.required_updates.length > 0 && (
                <ul className="adList">
                  {(mdtResult.required_updates as JsonObj[]).slice(0, 6).map((u, i) => (
                    <li key={String(u.update_id ?? i)}>
                      {String(u.description ?? u.type ?? JSON.stringify(u)).slice(0, 200)}
                    </li>
                  ))}
                </ul>
              )}
              {!presentation && <pre className="adSmallPre">{JSON.stringify(mdtResult, null, 2)}</pre>}
            </CollapsibleRaw>
          )}
          {!selectedAdmissionId && <div>点击左侧在院床位或右侧事件/LLM 行查看详情。</div>}
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
              <div className="scKeyValue">
                <span>Latest vitals</span>
                <strong>
                  HR {fmtCell(selectedVitals[0]?.heart_rate)} · MAP {fmtCell(selectedVitals[0]?.mean_arterial_pressure)} · SpO₂{" "}
                  {fmtCell(selectedVitals[0]?.spo2)}
                </strong>
              </div>
              <div className="scDivider" />

              <h3>近期生命体征</h3>
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
                      {selectedVitals.slice(0, presentation ? 6 : 20).map((v) => (
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

              <h3>近期干预</h3>
              {selectedInterventions.length === 0 ? (
                <p className="adMuted">No interventions yet.</p>
              ) : (
                <ul className="adList">
                  {selectedInterventions.slice(0, presentation ? 5 : 10).map((x) => (
                    <li key={String(x.event_id ?? x.detail_id)}>
                      <strong>{String(x.timestamp ?? "").slice(0, 19)}</strong> — {String(x.intervention_type)}: {String(x.description ?? "").slice(0, 120)}
                    </li>
                  ))}
                </ul>
              )}

              {!presentation && <AgentOutputBlock
                title="Latest bedside monitor output"
                rows={selectedBedside}
                presentation={presentation}
                emptyHint="No bedside_monitor output yet."
              />}
              {!presentation && <AgentOutputBlock
                title="Latest intervention tracker output"
                rows={selectedTrackerOutputs}
                presentation={presentation}
                emptyHint="No intervention_tracker output yet (needs intervention + follow-up data)."
              />}
              {!presentation && <AgentOutputBlock
                title="Latest patient memory output"
                rows={selectedMemory}
                presentation={presentation}
                emptyHint="No patient_memory output yet."
              />}
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

        {!presentation && <div className="scPanel">
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
        </div>}
      </section>

      {!presentation && <section className="scPanel">
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
          <strong>{(displayedStep?.agent_delta_summary as JsonObj)?.triggered_agent_names ? JSON.stringify((displayedStep?.agent_delta_summary as JsonObj).triggered_agent_names) : "—"}</strong>
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
      </section>}

      {presentation && lastStep && (
        <section className="scPanel adHintFooter">
          <p className="adMuted">Switch to <strong>Debug</strong> mode to inspect full JSON, timeline payloads, and LLM audit fields.</p>
        </section>
      )}
    </div>
  );
}
