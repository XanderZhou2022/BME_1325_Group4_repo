import type { JsonObj } from "../types";

export type StepEventItem = {
  index: number;
  type: string;
  admission_id: string;
  bed_id: string;
  patient_id: string;
  title: string;
  details: string[];
  tone: "admin" | "clinical" | "neutral";
};

function lookupIds(
  admissionId: string,
  byAdmission: Map<string, { bed_id: string; patient_id: string }>
): { bed_id: string; patient_id: string } {
  const hit = byAdmission.get(admissionId);
  return { bed_id: hit?.bed_id ?? "—", patient_id: hit?.patient_id ?? "—" };
}

function fmtNum(v: unknown): string {
  if (v === null || v === undefined) return "—";
  return String(v);
}

function formatVital(req: JsonObj): string[] {
  const lines: string[] = [];
  if (req.heart_rate != null) lines.push(`心率 HR ${fmtNum(req.heart_rate)} bpm`);
  if (req.mean_arterial_pressure != null) lines.push(`平均动脉压 MAP ${fmtNum(req.mean_arterial_pressure)} mmHg`);
  if (req.respiratory_rate != null) lines.push(`呼吸频率 RR ${fmtNum(req.respiratory_rate)} /min`);
  if (req.spo2 != null) lines.push(`血氧 SpO₂ ${fmtNum(req.spo2)}%`);
  if (req.temperature != null) lines.push(`体温 ${fmtNum(req.temperature)} °C`);
  if (req.gcs != null) lines.push(`GCS ${fmtNum(req.gcs)}`);
  if (req.priority) lines.push(`优先级：${String(req.priority)}`);
  return lines.length ? lines : ["已写入一条生命体征记录"];
}

function formatLab(req: JsonObj): string[] {
  const lab = String(req.lab_type ?? "检验");
  const val = fmtNum(req.value);
  const unit = req.unit ? ` ${req.unit}` : "";
  const flag = req.abnormal_flag ? `，异常标记：${String(req.abnormal_flag)}` : "";
  return [`检验项目：${lab}`, `结果：${val}${unit}${flag}`];
}

function formatIntervention(req: JsonObj): string[] {
  const lines = [
    `干预类型：${String(req.intervention_type ?? "—")}`,
    `描述：${String(req.description ?? "—")}`,
  ];
  if (req.dosage != null) lines.push(`剂量：${fmtNum(req.dosage)} ${String(req.unit ?? "")}`.trim());
  return lines;
}

function formatDispatch(dr: JsonObj | undefined): string[] {
  if (!dr) return [];
  const agents = Array.isArray(dr.triggered_agents) ? (dr.triggered_agents as string[]).join(" → ") : "";
  const ms = dr.total_chain_ms != null ? `${dr.total_chain_ms} ms` : "—";
  const lines = [`Agent 链耗时：${ms}`];
  if (agents) lines.push(`触发：${agents}`);
  const steps = dr.steps as JsonObj[] | undefined;
  if (Array.isArray(steps) && steps.length) {
    lines.push(
      ...steps.map(
        (s) =>
          `  · ${String(s.step_name)}：${s.status ?? "ok"}${s.duration_ms != null ? ` (${s.duration_ms} ms)` : ""}`
      )
    );
  }
  return lines;
}

function pickBridge(sub: JsonObj): JsonObj {
  const bridge = sub.bridge;
  return bridge && typeof bridge === "object" ? (bridge as JsonObj) : {};
}

function formatMdtFulfilled(sub: JsonObj): string[] {
  const bridge = pickBridge(sub);
  const judgment = (bridge.mdt_judgment && typeof bridge.mdt_judgment === "object" ? bridge.mdt_judgment : {}) as JsonObj;
  const updates = Array.isArray(bridge.required_updates) ? bridge.required_updates : [];
  const lines = [
    `请求 ID：${String(sub.request_id ?? "—")}`,
    `请求：${String(sub.request ?? "Request new MDT consultation")}`,
    `理由：${String(sub.reason ?? "—")}`,
    `触发 Agent：${String(sub.requested_by_agent ?? "—")}`,
    `会诊 ID：${String(sub.consultation_id ?? bridge.consultation_id ?? "—")}`,
    `状态：${String(judgment.status_level ?? bridge.mdt_output_type ?? sub.mdt_output_type ?? "已完成")}`,
  ];
  if (judgment.surgery_ready != null) lines.push(`手术准备：${String(judgment.surgery_ready)}`);
  if (bridge.case_summary) lines.push(`摘要：${String(bridge.case_summary).slice(0, 160)}`);
  if (updates.length > 0) {
    lines.push(`需更新事项：${updates.length} 项`);
    for (const item of updates.slice(0, 3)) {
      const u = item && typeof item === "object" ? (item as JsonObj) : {};
      lines.push(`  · ${String(u.description ?? u.type ?? JSON.stringify(item)).slice(0, 120)}`);
    }
  }
  return lines;
}

function formatMdtFailed(sub: JsonObj): string[] {
  return [
    `请求 ID：${String(sub.request_id ?? "—")}`,
    `请求：${String(sub.request ?? "Request new MDT consultation")}`,
    `理由：${String(sub.reason ?? "—")}`,
    `触发 Agent：${String(sub.requested_by_agent ?? "—")}`,
    `MDT 会诊失败：${String(sub.error ?? "未知错误")}`,
  ];
}

function formatGenericAgentRequest(sub: JsonObj): string[] {
  const lines: string[] = [];
  if (sub.request_id) lines.push(`请求 ID：${String(sub.request_id)}`);
  if (sub.request) lines.push(`请求：${String(sub.request)}`);
  if (sub.reason) lines.push(`理由：${String(sub.reason)}`);
  if (sub.requested_by_agent) lines.push(`触发 Agent：${String(sub.requested_by_agent)}`);
  if (sub.lab_type) lines.push(`检验项目：${String(sub.lab_type)}`);
  if (sub.error) lines.push(`错误：${String(sub.error)}`);
  if (sub.status) lines.push(`状态：${String(sub.status)}`);
  if (sub.mdt_output_type) lines.push(`输出类型：${String(sub.mdt_output_type)}`);
  return lines.length ? lines : ["Agent 请求已处理。"];
}

function titleForAgentRequest(type: string): string {
  if (type.includes("mdt") && type.includes("failed")) return "MDT 会诊请求失败";
  if (type.includes("mdt") && type.includes("fulfilled")) return "MDT 会诊请求已完成";
  if (type.includes("lab") && type.includes("fulfilled")) return "Agent 请求检验已完成";
  return "Agent 请求已处理";
}

export function buildStepEventItems(
  lastStep: JsonObj | null | undefined,
  admissions: { admission_id: string; patient_id: string; bed_id: string }[]
): StepEventItem[] {
  const wr = (lastStep?.event_write_result ?? {}) as JsonObj;
  const subs = (wr.sub_events as JsonObj[] | undefined) ?? [];
  if (!Array.isArray(subs) || subs.length === 0) return [];

  const byAdmission = new Map(admissions.map((a) => [a.admission_id, { bed_id: a.bed_id, patient_id: a.patient_id }]));

  return subs.map((sub, index) => {
    const type = String(sub.type ?? "unknown").trim();
    const admission_id = String(sub.admission_id ?? "");
    const ids = lookupIds(admission_id, byAdmission);
    const wrInner = (sub.write_result ?? {}) as JsonObj;
    const req = (sub.request_payload ?? {}) as JsonObj;
    const dr = wrInner.dispatch_result as JsonObj | undefined;

    if (type === "admission_create") {
      return {
        index: index + 1,
        type,
        admission_id,
        bed_id: String(wrInner.bed_id ?? ids.bed_id),
        patient_id: String(wrInner.patient_id ?? ids.patient_id),
        title: "新患者收治入院",
        details: [
          `床位：${String(wrInner.bed_id ?? ids.bed_id)}`,
          `入院 ID：${admission_id}`,
          `患者：${String(wrInner.patient_id ?? ids.patient_id)}`,
          `严重程度：${String(wrInner.severity ?? "—")}`,
        ],
        tone: "admin",
      };
    }

    if (type === "admissions_batch_complete") {
      const created = Number((sub as JsonObj).admissions_created ?? 0);
      const dis = Number((sub as JsonObj).discharges ?? 0);
      return {
        index: index + 1,
        type,
        admission_id: "",
        bed_id: "",
        patient_id: "",
        title: "出入院批次完成",
        details: [`新收治 ${created} 人`, `出院 ${dis} 人`, "随后才启动患者级 Agent"],
        tone: "admin",
      };
    }

    if (type === "ward_coordinator_batch") {
      return {
        index: index + 1,
        type,
        admission_id: String((sub as JsonObj).anchor_admission_id ?? ""),
        bed_id: "",
        patient_id: "",
        title: "全病房 ward_coordinator",
        details: [
          `状态: ${String((sub as JsonObj).status ?? "—")}`,
          `队列: ${String((sub as JsonObj).queue_size ?? "—")} 人`,
          `负荷: ${String((sub as JsonObj).ward_load_indicator ?? "—")}`,
        ],
        tone: "admin",
      };
    }

    if (type === "admission_discharge") {
      return {
        index: index + 1,
        type,
        admission_id,
        bed_id: ids.bed_id,
        patient_id: ids.patient_id,
        title: "患者出院",
        details: [`入院 ID：${admission_id}`, `床位：${ids.bed_id}`],
        tone: "admin",
      };
    }

    if (type === "admission_transfer_out") {
      const reasons = Array.isArray(sub.transfer_reasons) ? (sub.transfer_reasons as string[]) : [];
      const bridge = (sub.bridge_response ?? {}) as JsonObj;
      return {
        index: index + 1,
        type,
        admission_id,
        bed_id: ids.bed_id,
        patient_id: ids.patient_id,
        title: "转出至住院部",
        details: [
          `转出原因：${String(sub.reason ?? "—")}`,
          ...reasons.slice(0, 4).map((r) => `依据：${r}`),
          bridge.assigned_bed ? `住院部床位：${String(bridge.assigned_bed)}` : "住院部床位：待分配",
          bridge.assigned_room ? `病房：${String(bridge.assigned_room)}` : "",
        ].filter(Boolean),
        tone: "admin",
      };
    }

    if (type === "admission_transfer_blocked") {
      const reasons = Array.isArray(sub.transfer_reasons) ? (sub.transfer_reasons as string[]) : [];
      return {
        index: index + 1,
        type,
        admission_id,
        bed_id: ids.bed_id,
        patient_id: ids.patient_id,
        title: "转出住院部受阻",
        details: [
          String(sub.reason ?? "住院部桥接不可用"),
          ...reasons.slice(0, 3).map((r) => `临床依据：${r}`),
        ],
        tone: "admin",
      };
    }

    if (type === "vital_sign") {
      return {
        index: index + 1,
        type,
        admission_id,
        bed_id: ids.bed_id,
        patient_id: ids.patient_id,
        title: "生命体征更新",
        details: [...formatVital(req), ...formatDispatch(dr)],
        tone: "clinical",
      };
    }

    if (type === "lab") {
      return {
        index: index + 1,
        type,
        admission_id,
        bed_id: ids.bed_id,
        patient_id: ids.patient_id,
        title: "检验报告",
        details: [...formatLab(req), ...formatDispatch(dr)],
        tone: "clinical",
      };
    }

    if (type === "intervention") {
      return {
        index: index + 1,
        type,
        admission_id,
        bed_id: ids.bed_id,
        patient_id: ids.patient_id,
        title: "治疗干预",
        details: [...formatIntervention(req), ...formatDispatch(dr)],
        tone: "clinical",
      };
    }

    if (type.includes("agent_request_mdt_fulfilled")) {
      return {
        index: index + 1,
        type,
        admission_id,
        bed_id: ids.bed_id,
        patient_id: ids.patient_id,
        title: "MDT 会诊请求已完成",
        details: formatMdtFulfilled(sub),
        tone: "clinical",
      };
    }

    if (type.includes("agent_request_mdt_failed")) {
      return {
        index: index + 1,
        type,
        admission_id,
        bed_id: ids.bed_id,
        patient_id: ids.patient_id,
        title: "MDT 会诊请求失败",
        details: formatMdtFailed(sub),
        tone: "clinical",
      };
    }

    if (type.includes("agent_request_lab_fulfilled")) {
      return {
        index: index + 1,
        type,
        admission_id,
        bed_id: ids.bed_id,
        patient_id: ids.patient_id,
        title: "Agent 请求检验已完成",
        details: [
          `请求 ID：${String(sub.request_id ?? "—")}`,
          `请求：${String(sub.request ?? `Request new lab test: ${String(sub.lab_type ?? "—")}`)}`,
          `理由：${String(sub.reason ?? "—")}`,
          `触发 Agent：${String(sub.requested_by_agent ?? "—")}`,
          `检验项目：${String(sub.lab_type ?? "—")}`,
          ...formatDispatch(sub.dispatch_result as JsonObj | undefined),
        ],
        tone: "clinical",
      };
    }

    if (type.startsWith("agent_request_")) {
      return {
        index: index + 1,
        type,
        admission_id,
        bed_id: ids.bed_id,
        patient_id: ids.patient_id,
        title: titleForAgentRequest(type),
        details: formatGenericAgentRequest(sub),
        tone: "clinical",
      };
    }

    return {
      index: index + 1,
      type,
      admission_id,
      bed_id: ids.bed_id,
      patient_id: ids.patient_id,
      title: type,
      details: [`事件类型：${type}`, "详情请切换 Debug 模式查看。"],
      tone: "neutral",
    };
  });
}

export function bedIdsInStepEvents(items: StepEventItem[]): Set<string> {
  return new Set(items.map((i) => i.bed_id).filter((b) => b && b !== "—"));
}
