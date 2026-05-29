const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

async function request(path: string, options?: RequestInit) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API Error ${res.status}: ${text}`);
  }
  return res.json();
}

export const api = {
  base: BASE_URL,

  async listTables(): Promise<string[]> {
    return request('/api/tables');
  },

  async getTable(name: string, limit: number) {
    return request(`/api/table/${name}?limit=${limit}`);
  },

  async getCurrentState(admissionId: string) {
    return request(`/api/patient/${admissionId}/state`);
  },

  async getVitals(admissionId: string, limit: number) {
    return request(`/api/patient/${admissionId}/vitals?limit=${limit}`);
  },

  async getInterventions(admissionId: string, limit: number) {
    return request(`/api/patient/${admissionId}/interventions?limit=${limit}`);
  },

  async getRisks(admissionId: string, limit: number) {
    return request(`/api/patient/${admissionId}/risks?limit=${limit}`);
  },

  async getAgentOutputs(admissionId: string, agent: string, limit: number) {
    return request(`/api/patient/${admissionId}/outputs?agent=${agent}&limit=${limit}`);
  },

  async createAdmission(data: any) {
    return request('/api/admission', { method: 'POST', body: JSON.stringify(data) });
  },

  async updateAdmissionStatus(admissionId: string, data: any) {
    return request(`/api/admission/${admissionId}/status`, { method: 'POST', body: JSON.stringify(data) });
  },

  async postVital(admissionId: string, data: any) {
    return request(`/api/patient/${admissionId}/vital`, { method: 'POST', body: JSON.stringify(data) });
  },

  async postIntervention(admissionId: string, data: any) {
    return request(`/api/patient/${admissionId}/intervention`, { method: 'POST', body: JSON.stringify(data) });
  },

  async runPipeline(data: any) {
    return request('/api/pipeline', { method: 'POST', body: JSON.stringify(data) });
  }
};