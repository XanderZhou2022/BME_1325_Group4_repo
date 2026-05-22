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

export function buildStepEventItems(
  lastStep: JsonObj | null | undefined,
  admissions: { admission_id: string; patient_id: string; bed_id: string }[]
): StepEventItem[] {
  const wr = (lastStep?.event_write_result ?? {}) as JsonObj;
  const subs = (wr.sub_events as JsonObj[] | undefined) ?? [];
  if (!Array.isArray(subs) || subs.length === 0) return [];

  const byAdmission = new Map(admissions.map((a) => [a.admission_id, { bed_id: a.bed_id, patient_id: a.patient_id }]));

  return subs.map((sub, index) => {
    const type = String(sub.type ?? "unknown");
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

    return {
      index: index + 1,
      type,
      admission_id,
      bed_id: ids.bed_id,
      patient_id: ids.patient_id,
      title: type,
      details: [JSON.stringify(sub).slice(0, 300)],
      tone: "neutral",
    };
  });
}

export function bedIdsInStepEvents(items: StepEventItem[]): Set<string> {
  return new Set(items.map((i) => i.bed_id).filter((b) => b && b !== "—"));
}
