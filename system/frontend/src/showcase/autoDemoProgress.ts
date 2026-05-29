import type { JsonObj } from "../types";

export type DemoProgressEvent = JsonObj & {
  type: string;
  ts?: string;
};

export function formatProgressLine(ev: DemoProgressEvent): string {
  const t = new Date(ev.ts ? String(ev.ts) : 0).toLocaleTimeString("zh-CN", { hour12: false });
  const prefix = t !== "Invalid Date" ? `[${t}] ` : "";
  switch (ev.type) {
    case "step_plan":
      return `${prefix}下一步：仿真 ${String(ev.sim_before ?? "—")} → ${String(ev.sim_after ?? "—")}（第 ${ev.step_index} 步，${ev.active_patients} 位在院患者并行处理）`;
    case "ward_batch_start":
      return `${prefix}${String(ev.message ?? "全病房 Agent 批次开始…")}`;
    case "ward_batch_done": {
      const st = ev.status === "error" ? "失败" : "完成";
      return `${prefix}ward_coordinator 全病房批次${st}，队列 ${ev.queue_size ?? "—"} 人，${ev.duration_ms ?? "?"}ms`;
    }
    case "phase":
      return `${prefix}${String(ev.message ?? "处理中…")}`;
    case "patient_clinical_start":
      return `${prefix}患者 ${String(ev.admission_id)} / 床 ${String(ev.bed_id)}：写入临床事件「${String(ev.event_type)}」并启动 Agent 链`;
    case "patient_clinical_done":
      return `${prefix}患者 ${String(ev.admission_id)} / 床 ${String(ev.bed_id)}：「${String(ev.event_type)}」分析完成，${ev.duration_ms ?? "?"}ms`;
    case "agent_start":
      return `${prefix}Agent「${String(ev.agent_name)}」开始（入院 ${String(ev.admission_id)}）`;
    case "agent_done": {
      const st = ev.status === "error" ? "失败" : "完成";
      return `${prefix}Agent「${String(ev.agent_name)}」${st}，耗时 ${ev.duration_ms}ms`;
    }
    case "agent_requests_start":
      return `${prefix}检查 Agent 待办：入院 ${String(ev.admission_id ?? "—")} / 床 ${String(ev.bed_id ?? "—")}`;
    case "agent_request_fulfilled":
      return `${prefix}Agent 待办已执行：${String(ev.request ?? ev.request_type ?? "—")}；理由：${String(ev.reason ?? "—")}；来源：${String(ev.requested_by_agent ?? "—")}`;
    case "knowledge_start":
      return `${prefix}「${String(ev.agent_name)}」检索知识库（领域：${String(ev.domains ?? "—")}）…`;
    case "knowledge_done":
      return `${prefix}「${String(ev.agent_name)}」知识检索完成：${ev.card_count} 条卡片${ev.card_ids ? ` [${(ev.card_ids as string[]).slice(0, 3).join(", ")}${(ev.card_ids as string[]).length > 3 ? "…" : ""}]` : ""}（${ev.duration_ms}ms）`;
    case "llm_start":
      return `${prefix}「${String(ev.agent_name)}」调用 LLM：${String(ev.task_name)}（模型 ${String(ev.model ?? "—")}）…`;
    case "llm_end": {
      const ok = ev.llm_used ? "成功" : ev.fallback_used ? "fallback" : "未用 LLM";
      return `${prefix}「${String(ev.agent_name)}」LLM 结束：${ok}，${ev.duration_ms}ms${ev.error ? ` — ${String(ev.error).slice(0, 80)}` : ""}`;
    }
    case "complete":
      return `${prefix}本步全部完成`;
    case "error":
      return `${prefix}错误：${String(ev.message ?? "unknown")}`;
    default:
      return `${prefix}${ev.type}: ${JSON.stringify(ev)}`;
  }
}

export function progressKind(ev: DemoProgressEvent): "info" | "agent" | "knowledge" | "llm" | "done" | "error" {
  if (ev.type === "error") return "error";
  if (ev.type === "complete") return "done";
  if (ev.type === "llm_start" || ev.type === "llm_end") return "llm";
  if (ev.type === "knowledge_start" || ev.type === "knowledge_done") return "knowledge";
  if (ev.type === "ward_batch_start" || ev.type === "ward_batch_done") return "agent";
  if (ev.type?.startsWith("agent_") || ev.type === "patient_clinical_start" || ev.type === "patient_clinical_done") return "agent";
  return "info";
}
