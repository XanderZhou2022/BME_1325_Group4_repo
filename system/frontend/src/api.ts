import type { Admission, JsonObj, TablePreview } from "./types";

const runtimeHost = typeof window !== "undefined" ? window.location.hostname : "127.0.0.1";
const API_BASE = import.meta.env.VITE_API_BASE ?? `http://${runtimeHost}:8000/api/v1`;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return (await res.json()) as T;
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

  getOrchestratorRuns: (limit = 20) =>
    request<JsonObj[]>(`/orchestrator/runs?limit=${limit}`),

  getOrchestratorRun: (runId: string) =>
    request<JsonObj>(`/orchestrator/runs/${encodeURIComponent(runId)}`),
};
