import type { Admission, JsonObj, TablePreview } from "./types";

const runtimeHost = typeof window !== "undefined" ? window.location.hostname : "127.0.0.1";
const API_BASE = import.meta.env.VITE_API_BASE ?? `http://${runtimeHost}:8000/api/v1`;

function unwrapContract<T>(raw: unknown): T {
  if (raw !== null && typeof raw === "object" && "ok" in raw && "data" in raw) {
    const env = raw as { ok: boolean; data: T; error: { code: string; message: string; details?: unknown } | null };
    if (!env.ok) {
      const e = env.error;
      const msg = e ? `${e.code}: ${e.message}` : "request failed";
      throw new Error(msg);
    }
    return env.data;
  }
  return raw as T;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  const text = await res.text();
  let raw: unknown;
  try {
    raw = text ? JSON.parse(text) : null;
  } catch {
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${text}`);
    throw new Error("Invalid JSON response");
  }
  if (!res.ok) {
    const fromContract =
      raw !== null && typeof raw === "object" && "error" in raw
        ? (raw as { error?: { code?: string; message?: string } }).error
        : undefined;
    if (fromContract?.message) {
      throw new Error(`${fromContract.code ?? res.status}: ${fromContract.message}`);
    }
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return unwrapContract<T>(raw);
}

export const api = {
  base: API_BASE,

  listTables: () => request<string[]>("/ops/db/tables"),
  getTable: (tableName: string, limit = 100) =>
    request<TablePreview>(`/ops/db/tables/${encodeURIComponent(tableName)}?limit=${limit}`),

  createAdmission: (payload: JsonObj) =>
    request<Admission>("/admissions", { method: "POST", body: JSON.stringify(payload) }),

  updateAdmissionStatus: (admissionId: string, payload: JsonObj) =>
    request<Admission>(`/admissions/${encodeURIComponent(admissionId)}/status`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  postVital: (admissionId: string, payload: JsonObj) =>
    request<JsonObj>(`/admissions/${encodeURIComponent(admissionId)}/events/vital_sign`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  postIntervention: (admissionId: string, payload: JsonObj) =>
    request<JsonObj>(`/admissions/${encodeURIComponent(admissionId)}/events/intervention`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  runPipeline: (payload: JsonObj) =>
    request<JsonObj>("/orchestrator/demo-run", { method: "POST", body: JSON.stringify(payload) }),

  getCurrentState: (admissionId: string) =>
    request<JsonObj>(`/admissions/${encodeURIComponent(admissionId)}/state/current`),

  getVitals: (admissionId: string, limit = 50) =>
    request<JsonObj[]>(`/admissions/${encodeURIComponent(admissionId)}/vitals?limit=${limit}`),

  getInterventions: (admissionId: string, limit = 50) =>
    request<JsonObj[]>(`/admissions/${encodeURIComponent(admissionId)}/interventions?limit=${limit}`),

  getRisks: (admissionId: string, limit = 50) =>
    request<JsonObj[]>(`/admissions/${encodeURIComponent(admissionId)}/risks?limit=${limit}`),

  requestMdtConsultation: (admissionId: string, body?: JsonObj) =>
    request<JsonObj>(`/admissions/${encodeURIComponent(admissionId)}/consultations/mdt`, {
      method: "POST",
      body: JSON.stringify(body ?? { reason: "ICU manual MDT consultation", use_api: false }),
    }),

  getMdtExport: (admissionId: string) =>
    request<JsonObj>(`/admissions/${encodeURIComponent(admissionId)}/consultations/mdt/export`),

  getLatestMdtConsultation: (admissionId: string) =>
    request<JsonObj>(`/admissions/${encodeURIComponent(admissionId)}/consultations/mdt/latest`),

  getAgentOutputs: (admissionId: string, agentName?: string, limit = 30) => {
    const q = agentName
      ? `?agent_name=${encodeURIComponent(agentName)}&limit=${limit}`
      : `?limit=${limit}`;
    return request<JsonObj[]>(`/admissions/${encodeURIComponent(admissionId)}/agent_outputs${q}`);
  },

  getAgentEvents: (admissionId: string, producerAgent?: string, limit = 60) => {
    const q = producerAgent
      ? `?producer_agent=${encodeURIComponent(producerAgent)}&limit=${limit}`
      : `?limit=${limit}`;
    return request<JsonObj[]>(`/admissions/${encodeURIComponent(admissionId)}/agent_events${q}`);
  },

  generateFamilyDraft: (admissionId: string, draftType = "daily_family_update_zh") =>
    request<JsonObj>("/agents/compassion-family/draft", {
      method: "POST",
      body: JSON.stringify({ admission_id: admissionId, draft_type: draftType }),
    }),

  getOrchestratorRuns: (limit = 20) =>
    request<JsonObj[]>(`/orchestrator/runs?limit=${limit}`),

  getOrchestratorRun: (runId: string) =>
    request<JsonObj>(`/orchestrator/runs/${encodeURIComponent(runId)}`),

  demoAutoReset: () => request<JsonObj>("/demo/auto/reset", { method: "POST" }),
  demoAutoNext: () => request<JsonObj>("/demo/auto/next", { method: "POST" }),
  demoAutoAddPatient: () => request<JsonObj>("/demo/auto/admit-random", { method: "POST" }),
  demoAutoDischargePatient: (admissionId: string) =>
    request<JsonObj>(`/demo/auto/admissions/${encodeURIComponent(admissionId)}/discharge`, { method: "POST" }),
  demoAutoState: () => request<JsonObj>("/demo/auto/state"),
  demoAutoTimeline: (limit = 100) => request<JsonObj>(`/demo/auto/timeline?limit=${limit}`),

  /** NDJSON stream: progress events, then `{ type: "result", data }` or `{ type: "error" }`. */
  demoAutoNextStream: async (onEvent: (ev: JsonObj) => void): Promise<JsonObj> => {
    const res = await fetch(`${API_BASE}/demo/auto/next/stream`, {
      method: "POST",
      headers: { Accept: "application/x-ndjson" },
    });
    if (!res.ok) {
      const text = await res.text();
      let msg = `${res.status} ${res.statusText}`;
      try {
        const raw = JSON.parse(text) as { error?: { message?: string; code?: string } };
        if (raw.error?.message) msg = `${raw.error.code ?? res.status}: ${raw.error.message}`;
      } catch {
        if (text) msg = text.slice(0, 200);
      }
      throw new Error(msg);
    }
    const body = res.body;
    if (!body) throw new Error("No response body");
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let result: JsonObj | null = null;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop() ?? "";
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        const ev = JSON.parse(trimmed) as JsonObj;
        if (ev.type === "result" && ev.data) {
          result = ev.data as JsonObj;
        } else if (ev.type === "error") {
          throw new Error(String(ev.message ?? "next step stream failed"));
        } else {
          onEvent(ev);
        }
      }
    }
    const tail = buf.trim();
    if (tail) {
      const ev = JSON.parse(tail) as JsonObj;
      if (ev.type === "result" && ev.data) result = ev.data as JsonObj;
      else if (ev.type === "error") throw new Error(String(ev.message ?? "next step stream failed"));
      else onEvent(ev);
    }
    if (!result) throw new Error("Stream ended without result payload");
    return result;
  },
};
