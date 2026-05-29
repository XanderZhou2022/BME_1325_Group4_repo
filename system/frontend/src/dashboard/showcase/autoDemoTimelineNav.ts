import type { JsonObj } from "../types";
import type { DemoNextFull } from "./autoDemoTypes";

export type TimelineStepEntry = {
  step_index: number;
  item: JsonObj;
  step: DemoNextFull;
};

export function timelineItemToDemoNext(item: JsonObj): DemoNextFull | null {
  const result = item.result as JsonObj | undefined;
  if (!result || typeof result !== "object") return null;
  return result as DemoNextFull;
}

export function buildTimelineSteps(timeline: JsonObj[]): TimelineStepEntry[] {
  const seen = new Set<number>();
  const entries: TimelineStepEntry[] = [];
  for (const item of timeline) {
    const step_index = Number(item.step_index);
    if (!Number.isFinite(step_index) || seen.has(step_index)) continue;
    const step = timelineItemToDemoNext(item);
    if (!step) continue;
    seen.add(step_index);
    entries.push({ step_index, item, step });
  }
  return entries.sort((a, b) => a.step_index - b.step_index);
}

export function resolveViewPosition(
  steps: TimelineStepEntry[],
  viewingStepIndex: number | null,
  latestStepIndex: number | null
): { listIndex: number; step_index: number | null; isLatest: boolean } {
  if (steps.length === 0) {
    return { listIndex: -1, step_index: latestStepIndex, isLatest: true };
  }
  if (viewingStepIndex == null) {
    const last = steps[steps.length - 1];
    return { listIndex: steps.length - 1, step_index: last.step_index, isLatest: latestStepIndex == null || last.step_index >= latestStepIndex };
  }
  const idx = steps.findIndex((s) => s.step_index === viewingStepIndex);
  if (idx < 0) {
    const last = steps[steps.length - 1];
    return { listIndex: steps.length - 1, step_index: last.step_index, isLatest: true };
  }
  const isLatest = latestStepIndex != null ? viewingStepIndex >= latestStepIndex : idx === steps.length - 1;
  return { listIndex: idx, step_index: viewingStepIndex, isLatest };
}

export function formatSimTimeLabel(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString("zh-CN", { hour12: false });
  } catch {
    return iso;
  }
}
