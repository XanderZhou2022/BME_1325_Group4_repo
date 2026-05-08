# Frontend API Examples (Cross-machine)

## 1) Base URL

```text
http://<backend-lan-ip>:8000
```

Example:

```text
http://192.168.1.20:8000
```

## 2) TypeScript fetch wrapper

```ts
const BASE_URL = "http://192.168.1.20:8000";

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`HTTP ${resp.status}: ${text}`);
  }
  return (await resp.json()) as T;
}
```

## 3) Write a vital sign event

```ts
await api(`/api/v1/admissions/ICU-ADM-0001/events/vital_sign`, {
  method: "POST",
  body: JSON.stringify({
    timestamp: new Date().toISOString(),
    source: "monitor",
    priority: "normal",
    heart_rate: 108,
    mean_arterial_pressure: 64,
    spo2: 92,
  }),
});
```

## 4) Trigger core agents

```ts
await api(`/agents/bedside-monitor/analyze`, {
  method: "POST",
  body: JSON.stringify({ admission_id: "ICU-ADM-0001", analysis_window: "last_4h" }),
});

await api(`/agents/intervention-tracker/evaluate`, {
  method: "POST",
  body: JSON.stringify({ admission_id: "ICU-ADM-0001", intervention_id: "INT-20260508-10002" }),
});

await api(`/agents/risk-sentinel/evaluate`, {
  method: "POST",
  body: JSON.stringify({ admission_id: "ICU-ADM-0001", max_events: 200 }),
});
```

## 5) Read data for UI

```ts
const currentState = await api(`/api/v1/admissions/ICU-ADM-0001/state/current`);
const alerts = await api(`/api/v1/admissions/ICU-ADM-0001/alerts`);
const risks = await api(`/api/v1/admissions/ICU-ADM-0001/risks`);
const agentEvents = await api(`/api/v1/admissions/ICU-ADM-0001/agent_events?limit=50`);
```

## 6) Retry guidance

- Use request timeout 5-10 seconds for reads, 10-20 seconds for writes.
- For `5xx` errors, retry with exponential backoff (e.g., 500ms, 1s, 2s; max 3 tries).
- Do not blindly retry `4xx` (usually payload/ID issue).

## 7) Full pipeline demo run

```ts
const run = await api(`/api/v1/orchestrator/demo-run`, {
  method: "POST",
  body: JSON.stringify({
    admission_id: "ICU-ADM-0001",
    memory_window_hours: 24,
    top_k: 10,
  }),
});

const runDetail = await api(`/api/v1/orchestrator/runs/${run.run_id}`);
console.log(runDetail.step_results);
```

## 8) Dynamic new admission flow

```ts
// after frontend writes events for a newly active admission,
// call run_all_active to include it automatically:
await api(`/api/v1/orchestrator/demo-run`, {
  method: "POST",
  body: JSON.stringify({ run_all_active: true }),
});
```
