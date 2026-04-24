可以，给你一套**最短可复现**的完整联动跑法（含可见输出）。

## 1) 启动后端（Terminal A）

在 `system/backend/api`：

```powershell
$env:ICU_PG_DSN="dbname=icu_agent user=postgres password=123456 host=localhost port=5432"
$env:ICU_CORS_ORIGINS="*"
uvicorn --app-dir . app.main:app --host 0.0.0.0 --port 8000
```

先确认健康：

```powershell
curl http://127.0.0.1:8000/api/v1/ops/db-health
```

---

## 2) 准备一个 active admission（可选）

如果你库里已有 active admission，可以跳过。  
先查一个 `admission_id`：

```powershell
curl http://127.0.0.1:8000/api/v1/admissions?status=active
```

拿到 `admission_id`（下面用 `adm_xxx` 代替）。

---

## 3) 触发事件链（关键）

### 3.1 发 vital_sign 事件（触发 bedside -> memory -> risk -> summary -> ward）

```powershell
curl -X POST "http://127.0.0.1:8000/api/v1/admissions/adm_xxx/events/vital_sign" `
  -H "Content-Type: application/json" `
  -d "{\"timestamp\":\"2026-04-24T10:00:00Z\",\"heart_rate\":122,\"mean_arterial_pressure\":58,\"respiratory_rate\":28,\"temperature\":38.5,\"spo2\":90,\"gcs\":13}"
```

### 3.2 再发 intervention（触发 intervention_tracker 分支）

```powershell
curl -X POST "http://127.0.0.1:8000/api/v1/admissions/adm_xxx/events/intervention" `
  -H "Content-Type: application/json" `
  -d "{\"timestamp\":\"2026-04-24T10:05:00Z\",\"intervention_type\":\"fluid\",\"description\":\"500ml crystalloid bolus\",\"dosage\":500,\"unit\":\"ml\"}"
```

### 3.3 发 lab（触发 memory + 条件 risk/summarize）

```powershell
curl -X POST "http://127.0.0.1:8000/api/v1/admissions/adm_xxx/events/lab" `
  -H "Content-Type: application/json" `
  -d "{\"timestamp\":\"2026-04-24T10:08:00Z\",\"lab_type\":\"lactate\",\"value\":4.2,\"unit\":\"mmol/L\",\"abnormal_flag\":\"high\"}"
```

---

## 4) 看“联动输出”是否都落库

### 4.1 看 agent outputs（最直观）

```powershell
curl "http://127.0.0.1:8000/api/v1/admissions/adm_xxx/agent-outputs?limit=50"
```

你应该能看到这些 `agent_name`：
- `bedside_monitor`
- `intervention_tracker`
- `patient_memory`
- `risk_sentinel`
- `clinical_summary`
- 以及全局 `ward_coordinator`（锚定到某个 admission）

### 4.2 看 agent events（started/completed/ready）

```powershell
curl "http://127.0.0.1:8000/api/v1/admissions/adm_xxx/agent-events?limit=100"
```

---

## 5) 也可以直接跑一键 demo pipeline（补充）

```powershell
curl -X POST "http://127.0.0.1:8000/api/v1/orchestrator/demo-run" `
  -H "Content-Type: application/json" `
  -d "{\"admission_id\":\"adm_xxx\",\"run_all_active\":false,\"top_k\":10,\"memory_window_hours\":24}"
```

然后看运行记录：

```powershell
curl "http://127.0.0.1:8000/api/v1/orchestrator/runs?limit=10"
```

