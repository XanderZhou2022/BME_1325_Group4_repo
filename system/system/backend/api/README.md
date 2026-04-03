# ICU Agent API 使用指南

统一数据入口（FastAPI）。所有外部模块（时序模拟器、前端可视化、多智能体系统）**都应通过本 API 访问数据**，而不是直接连 PostgreSQL。

依赖的数据库结构与示例数据见：

- 建表脚本：`../测试数据库/init_core_tables.py`
- 种子数据：`../测试数据库/seed_test_data.py`
- 数据规范文档：`../数据规范/数据库使用规范.md`

---

## 1. 环境准备与启动

### 1.1 安装依赖

```bash
cd local/system/backend/api
python3 -m pip install -r requirements.txt
```

如遇到 SSL 证书错误，可加：

```bash
python3 -m pip install -r requirements.txt \
  --trusted-host pypi.org --trusted-host files.pythonhosted.org
```

### 1.2 配置数据库连接

API 通过环境变量 `ICU_PG_DSN` 读取 PostgreSQL 连接串（`app/config.py` 中的 `Settings.pg_dsn`）。

开发机示例（沿用之前建好的 `icu_agent` 库）：

```bash
export ICU_PG_DSN="dbname=icu_agent user=<你的系统用户名> host=localhost port=5432"
```

如果不设置，会使用默认：

```text
dbname=icu_agent user=zhou host=localhost port=5432
```

### 1.3 启动服务

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- 文档（Swagger）：`http://127.0.0.1:8000/docs`
- 健康检查：`GET /health`

---

## 2. API 总览

所有业务路由前缀为：`/api/v1`

### 2.1 写入类（事件驱动）

这三类是**唯一的写入入口**，后端内部会完成：

> 校验 admission 存在且 active → 写明细表  
> → 写 `events` → UPSERT `patient_state_current` → 写 `audit_logs`

- `POST /api/v1/admissions/{admission_id}/events/vital_sign`
  - 作用：写入一条生命体征事件（对齐 APACHE 字段）
  - 请求体：`VitalSignEventCreate`
  - 返回：`EventWriteResult`

- `POST /api/v1/admissions/{admission_id}/events/lab`
  - 作用：写入化验/检验结果
  - 请求体：`LabEventCreate`
  - 返回：`EventWriteResult`

- `POST /api/v1/admissions/{admission_id}/events/intervention`
  - 作用：写入治疗/干预事件
  - 请求体：`InterventionEventCreate`
  - 返回：`EventWriteResult`

### 2.2 状态与风险/告警查询

- `GET /api/v1/admissions/{admission_id}/state/current`
  - 读取当前聚合状态（`patient_state_current`）
  - 返回：`PatientStateCurrentOut`

- `GET /api/v1/admissions/{admission_id}/alerts`
  - 读取告警列表（`alerts`）
  - 返回：`AlertOut[]`

- `GET /api/v1/admissions/{admission_id}/risks`
  - 读取风险评估结果（`risk_assessments`）
  - 返回：`RiskAssessmentOut[]`

### 2.3 主数据与明细历史

- 主数据：
  - `GET /api/v1/patients/{patient_id}` → `PatientOut`
  - `GET /api/v1/beds/{bed_id}` → `BedOut`
  - `GET /api/v1/admissions/{admission_id}` → `AdmissionOut`

- 事件与明细：
  - `GET /api/v1/admissions/{admission_id}/events?limit=50` → `EventOut[]`
  - `GET /api/v1/admissions/{admission_id}/vitals?limit=100` → `VitalSignEventOut[]`
  - `GET /api/v1/admissions/{admission_id}/labs?limit=100` → `LabEventOut[]`
  - `GET /api/v1/admissions/{admission_id}/interventions?limit=100` → `InterventionEventOut[]`

- 状态快照与审计：
  - `GET /api/v1/admissions/{admission_id}/snapshots?limit=50` → `PatientStateSnapshotOut[]`
  - `GET /api/v1/admissions/{admission_id}/audit_logs?limit=100` → `AuditLogOut[]`

> `limit` 参数都有上限（例如 200/500），防止一次性拉太多记录。

---

## 3. 典型调用示例

### 3.1 用 curl 上传生命体征

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/admissions/adm1/events/vital_sign" \
  -H "Content-Type: application/json" \
  -d '{
    "timestamp": "2026-03-27T16:30:00+08:00",
    "source": "monitor",
    "priority": "normal",
    "heart_rate": 110,
    "mean_arterial_pressure": 66,
    "spo2": 93
  }'
```

返回（示例）：

```json
{
  "event_id": "evt_xxx",
  "detail_id": "vital_xxx",
  "admission_id": "adm1",
  "patient_id": "p1",
  "bed_id": "b1"
}
```

### 3.2 用 curl 查询当前状态

```bash
curl "http://127.0.0.1:8000/api/v1/admissions/adm1/state/current"
```

返回关键字段（简化）：

```json
{
  "admission_id": "adm1",
  "patient_id": "p1",
  "bed_id": "b1",
  "updated_at": "...",
  "current_vitals": {
    "heart_rate": 110,
    "mean_arterial_pressure": 66,
    "spo2": 93
  },
  "active_problems": ["septic_shock", "lab_lactate_high"],
  "active_risks": [
    { "risk_type": "shock", "severity": "critical" }
  ],
  "latest_interventions": [
    {
      "id": "intv_xxx",
      "intervention_type": "fluid",
      "description": "500ml saline bolus",
      "timestamp": "..."
    }
  ],
  "care_phase": "unstable"
}
```

### 3.3 用 Python（给 agent / 前端后端脚本）

```python
import requests
from datetime import datetime, timezone

BASE = "http://127.0.0.1:8000"

# 健康检查
print(requests.get(f"{BASE}/health").json())

# 上传一条生命体征
ts = datetime.now(timezone.utc).isoformat()
resp = requests.post(
    f"{BASE}/api/v1/admissions/adm1/events/vital_sign",
    json={
        "timestamp": ts,
        "source": "monitor",
        "priority": "normal",
        "heart_rate": 105,
        "mean_arterial_pressure": 64,
        "spo2": 92,
    },
)
print(resp.status_code, resp.json())

# 查询当前状态
state = requests.get(f"{BASE}/api/v1/admissions/adm1/state/current").json()
print("care_phase:", state["care_phase"])
print("vitals:", state["current_vitals"])
```

---

## 4. 给不同角色的使用建议

### 4.1 时序模拟器（数据生成端）

- **只调用写入接口**：
  - `POST /events/vital_sign`
  - `POST /events/lab`
  - `POST /events/intervention`
- 不直接操作数据库，不直接写 `patient_state_current` / `alerts` / `risk_assessments`。

### 4.2 Agent 层

- **典型读取入口**：
  - 以单床位（admission）为单位：
    - `GET /admissions/{admission_id}/state/current`
    - `GET /admissions/{admission_id}/vitals` / `labs` / `interventions`
    - `GET /admissions/{admission_id}/risks` / `alerts`
    - 如需病程回放 → `GET /admissions/{admission_id}/events` + `snapshots` + `audit_logs`
- 如无必要，**不要写入**，而是把推理结果返回给 orchestrator，后者再决定是否写 `risk_assessments` / `alerts`（之后可以扩展专门的写接口）。

### 4.3 前端 / 可视化

- ICU 总览：
  - 当前可以通过 `admissions` + `patient_state_current` + `alerts` 聚合；现阶段 API 按 admission 暴露，后续可增加房间/床位级聚合接口。
- 单床位详情：
  - 当前状态：`/state/current`
  - 时间线：`/events` + 各类明细 `/vitals` `/labs` `/interventions`
  - 告警面板：`/alerts`
  - 风险卡片：`/risks`

---

## 5. 版本与演进

- 当前 API 版本：`v1`（前缀 `/api/v1`）
- 未来如需对 schema 做不兼容修改，建议增加 `/api/v2` 前缀，保持旧版本可用一段时间。

更底层的数据字段定义与表结构，请始终以：

- `../数据规范/数据类型.md`
- `../数据规范/数据库使用规范.md`

为准。*** End Patch***}"/>
