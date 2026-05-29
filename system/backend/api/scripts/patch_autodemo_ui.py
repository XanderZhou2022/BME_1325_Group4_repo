# -*- coding: utf-8 -*-
from pathlib import Path

PAGE = Path(__file__).resolve().parents[3] / "frontend" / "src" / "showcase" / "AutoDemoPage.tsx"
CSS = Path(__file__).resolve().parents[3] / "frontend" / "src" / "showcase" / "showcase.css"
NAV = Path(__file__).resolve().parents[3] / "frontend" / "src" / "showcase" / "autoDemoTimelineNav.ts"

if not NAV.exists():
    raise SystemExit("autoDemoTimelineNav.ts missing")

t = PAGE.read_text(encoding="utf-8")

if "autoDemoTimelineNav" not in t:
    t = t.replace(
        'import { formatProgressLine, progressKind, type DemoProgressEvent } from "./autoDemoProgress";\nimport "./showcase.css";',
        'import { formatProgressLine, progressKind, type DemoProgressEvent } from "./autoDemoProgress";\n'
        'import { buildTimelineSteps, formatSimTimeLabel, resolveViewPosition } from "./autoDemoTimelineNav";\n'
        'import "./showcase.css";',
    )

if "viewingStepIndex" not in t:
    t = t.replace(
        "  const [plannedSimAfter, setPlannedSimAfter] = useState<string | null>(null);\n  const progressEndRef = useRef<HTMLDivElement>(null);",
        "  const [plannedSimAfter, setPlannedSimAfter] = useState<string | null>(null);\n"
        "  const [viewingStepIndex, setViewingStepIndex] = useState<number | null>(null);\n"
        "  const progressEndRef = useRef<HTMLDivElement>(null);",
    )

block = '''  const timelineSteps = useMemo(() => buildTimelineSteps(timeline), [timeline]);

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
    viewPosition.step_index != null &&
      !viewPosition.isLatest &&
      (state?.step_index ?? 0) > (viewPosition.step_index ?? 0)
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

'''

if "const timelineSteps = useMemo" not in t:
    t = t.replace("  const subEventChainTimings = useMemo(() => {", block + "  const subEventChainTimings = useMemo(() => {", 1)

t = t.replace(
    "    const wr = (lastStep?.event_write_result ?? {}) as JsonObj;",
    "    const wr = (displayedStep?.event_write_result ?? {}) as JsonObj;",
)
t = t.replace("  }, [lastStep]);", "  }, [displayedStep]);", 1)
t = t.replace(
    "    () => buildStepEventItems(lastStep as JsonObj | null, admissions),\n    [lastStep, admissions]",
    "    () => buildStepEventItems(displayedStep as JsonObj | null, admissions),\n    [displayedStep, admissions]",
)
t = t.replace(
    "    () => buildLlmTraceRows(lastStep?.agent_workflow_trace),\n    [lastStep?.agent_workflow_trace]",
    "    () => buildLlmTraceRows(displayedStep?.agent_workflow_trace),\n    [displayedStep?.agent_workflow_trace]",
)
t = t.replace(
    "  const agentOps = useMemo(() => (lastStep?.triggered_agents ?? []) as JsonObj[], [lastStep]);",
    "  const agentOps = useMemo(() => (displayedStep?.triggered_agents ?? []) as JsonObj[], [displayedStep]);",
)
t = t.replace(
    "  const narrativeLines = useMemo(() => buildStepNarrativeLines(lastStep), [lastStep]);",
    "  const narrativeLines = useMemo(() => buildStepNarrativeLines(displayedStep), [displayedStep]);",
)
t = t.replace(
    "  const pipelineNodes = useMemo(() => inferPipelineStatuses(lastStep), [lastStep]);",
    "  const pipelineNodes = useMemo(() => inferPipelineStatuses(displayedStep), [displayedStep]);",
)
t = t.replace(
    "  const currentEventBedId = useMemo(() => resolveCurrentEventBedId(lastStep, admissions), [lastStep, admissions]);",
    "  const currentEventBedId = useMemo(() => resolveCurrentEventBedId(displayedStep, admissions), [displayedStep, admissions]);",
)
t = t.replace(
    '  const currentEventAdmissionId = useMemo(() => String(lastStep?.admission_id ?? ""), [lastStep]);',
    '  const currentEventAdmissionId = useMemo(() => String(displayedStep?.admission_id ?? ""), [displayedStep]);',
)

# reset / nextStep
t = t.replace(
    "      setLastStep(null);\n      prevSigRef.current = \"\";",
    "      setLastStep(null);\n      setViewingStepIndex(null);\n      prevSigRef.current = \"\";",
)
t = t.replace(
    "      setLastStep(out);\n      setSelectedAgent(\"\");",
    "      setLastStep(out);\n      setViewingStepIndex(null);\n      setSelectedAgent(\"\");",
)
t = t.replace(
    "    } finally {\n      setLoading(false);\n      setPlannedSimAfter(null);\n    }",
    "    } finally {\n      setLoading(false);\n    }",
)

# progress banner -> fixed status bar
old_banner = """      {loading && (
        <div className="adStepWaitBanner adLiveProgress" role="status" aria-live="polite">
          <strong>
            本步进行中… 已等待 {workingSeconds}s
            {plannedSimAfter ? ` · 下一步仿真时间：${plannedSimAfter}` : ""}
          </strong>
          <div className="adLiveFeed">
            {progressLines.length === 0 ? (
              <p className="adMuted">正在连接进度流…</p>
            ) : (
              <ul className="adLiveFeedList">
                {progressLines.map((ev, i) => (
                  <li key={`${ev.ts ?? ""}-${ev.type}-${i}`} className={`adLiveLine adLive-${progressKind(ev)}`}>
                    {formatProgressLine(ev)}
                  </li>
                ))}
                <li ref={progressEndRef} />
              </ul>
            )}
          </div>
        </div>
      )}"""

new_banner = """      <div className="adStepStatusBar adLiveProgress" role="status" aria-live="polite">
        <strong>{statusBarTitle}</strong>
        <div className="adLiveFeed">
          {loading && progressLines.length === 0 ? (
            <p className="adMuted">正在连接进度流…</p>
          ) : progressLines.length === 0 ? (
            <p className="adMuted">本步详细进度将在点击 Next Step 后显示于此。</p>
          ) : (
            <ul className="adLiveFeedList">
              {progressLines.map((ev, i) => (
                <li key={`${ev.ts ?? ""}-${ev.type}-${i}`} className={`adLiveLine adLive-${progressKind(ev)}`}>
                  {formatProgressLine(ev)}
                </li>
              ))}
              <li ref={progressEndRef} />
            </ul>
          )}
        </div>
      </div>"""

if old_banner in t:
    t = t.replace(old_banner, new_banner, 1)
else:
    print("warn: banner block not found")

# step events header with arrows
old_h2 = """          <h2>
            本步事件 {state?.step_index != null ? `(Step #${state.step_index})` : ""}
          </h2>
          {!lastStep && <p className="adMuted">点击 Next Step 后，此处会列出本步全部子事件（收治/出院/体征/检验/干预）。</p>}
          {lastStep && stepEventItems.length === 0 && <p className="adMuted">本步无子事件记录。</p>}"""

new_h2 = """          <div className="adStepEventsHead">
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
          {!displayedStep && <p className="adMuted">点击 Next Step 后，此处会列出本步全部子事件（收治/出院/体征/检验/干预）。</p>}
          {displayedStep && stepEventItems.length === 0 && <p className="adMuted">本步无子事件记录。</p>}"""

if old_h2 in t:
    t = t.replace(old_h2, new_h2, 1)
else:
    print("warn: h2 block not found")

t = t.replace("(lastStep?.agent_delta_summary as JsonObj)", "(displayedStep?.agent_delta_summary as JsonObj)")
t = t.replace("JSON.stringify(lastStep ?? {}, null, 2)", "JSON.stringify(displayedStep ?? {}, null, 2)")

PAGE.write_text(t, encoding="utf-8")
print("AutoDemoPage patched")

css = CSS.read_text(encoding="utf-8")
if ".adStepStatusBar" not in css:
    css = css.replace(
        ".adStepWaitBanner {",
        ".adStepStatusBar {\n"
        "  position: sticky;\n"
        "  top: 0;\n"
        "  z-index: 30;\n"
        "  margin: 12px 0 16px;\n"
        "  padding: 12px 14px;\n"
        "  border-radius: 12px;\n"
        "  border: 1px solid #334155;\n"
        "  background: rgba(30, 41, 59, 0.95);\n"
        "  backdrop-filter: blur(6px);\n"
        "  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.35);\n"
        "}\n\n"
        ".adStepStatusBar strong {\n"
        "  color: #fde68a;\n"
        "  font-size: 15px;\n"
        "  display: block;\n"
        "}\n\n"
        ".adStepEventsHead {\n"
        "  display: flex;\n"
        "  align-items: center;\n"
        "  justify-content: space-between;\n"
        "  gap: 12px;\n"
        "  flex-wrap: wrap;\n"
        "  margin-bottom: 8px;\n"
        "}\n\n"
        ".adStepEventsTitle {\n"
        "  display: flex;\n"
        "  align-items: center;\n"
        "  gap: 10px;\n"
        "  margin: 0;\n"
        "  font-size: 1.15rem;\n"
        "}\n\n"
        ".adStepNavBtn {\n"
        "  width: 32px;\n"
        "  height: 32px;\n"
        "  border-radius: 8px;\n"
        "  border: 1px solid #475569;\n"
        "  background: #1e293b;\n"
        "  color: #e2e8f0;\n"
        "  font-size: 16px;\n"
        "  line-height: 1;\n"
        "  cursor: pointer;\n"
        "  padding: 0;\n"
        "}\n\n"
        ".adStepNavBtn:hover:not(:disabled) {\n"
        "  background: #334155;\n"
        "  border-color: #64748b;\n"
        "}\n\n"
        ".adStepNavBtn:disabled {\n"
        "  opacity: 0.35;\n"
        "  cursor: not-allowed;\n"
        "}\n\n"
        ".adStepNavHint {\n"
        "  font-size: 12px;\n"
        "  color: #94a3b8;\n"
        "}\n\n"
        ".adStepWaitBanner {",
    )
    CSS.write_text(css, encoding="utf-8")
    print("CSS patched")
else:
    print("CSS already has adStepStatusBar")
