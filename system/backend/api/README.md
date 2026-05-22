# ICU Agent API

**BME1325 contract v1.0 (HTTP)**

- Success payloads under `/api/v1/` are wrapped as `{ ok, data, error, trace_id }` (see `app/middleware/contract_envelope.py`).
- Transfer intake: `POST /api/v1/encounters/{encounter_id}/transfer` (receiver must use `to_group=groupC.icu`).
- Admissions: `POST /api/v1/admissions` requires contract-shaped IDs (`P-…`, `E-…`, …); optional `patient_profile` upserts the patient row.
- Env: `HOSPITAL_REDIS_*`（可选）；LLM 见 `api调用测试/.env`（`DASHSCOPE_*`）+ `ICU_LLM_ENABLED`（见 `docs/CONTRACT_v1_COMPLIANCE.md`）。

---

# ICU Agent API 浣跨敤鎸囧崡锛堜竴鏈燂級

缁熶竴鏁版嵁鍏ュ彛锛團astAPI锛夈€傛墍鏈夊閮ㄦā鍧楋紙鏃跺簭妯℃嫙鍣ㄣ€佸墠绔彲瑙嗗寲銆佸鏅鸿兘浣撶郴缁燂級**閮藉簲閫氳繃鏈?API 璁块棶鏁版嵁**锛岃€屼笉鏄洿鎺ヨ繛 PostgreSQL銆?
褰撳墠浠撳簱宸茬粺涓€涓荤嚎涓?`system/...`锛屽巻鍙插壇鏈?`system/system` 宸茬Щ闄ゃ€?

渚濊禆鐨勬暟鎹簱缁撴瀯涓庣ず渚嬫暟鎹锛?

- 寤鸿〃鑴氭湰锛歚../娴嬭瘯鏁版嵁搴?init_core_tables.py`
- 绉嶅瓙鏁版嵁锛歚../娴嬭瘯鏁版嵁搴?seed_test_data.py`
- 鏁版嵁瑙勮寖鏂囨。锛歚../鏁版嵁瑙勮寖/鏁版嵁搴撲娇鐢ㄨ鑼?md`

---

## 1. 鐜鍑嗗涓庡惎鍔?

### 1.1 瀹夎渚濊禆

```bash
cd local/system/backend/api
python3 -m pip install -r requirements.txt
```

濡傞亣鍒?SSL 璇佷功閿欒锛屽彲鍔狅細

```bash
python3 -m pip install -r requirements.txt \
  --trusted-host pypi.org --trusted-host files.pythonhosted.org
```

### 1.2 閰嶇疆鏁版嵁搴撹繛鎺?

API 閫氳繃鐜鍙橀噺 `ICU_PG_DSN` 璇诲彇 PostgreSQL 杩炴帴涓诧紙`app/config.py` 涓殑 `Settings.pg_dsn`锛夈€?

寮€鍙戞満绀轰緥锛堟部鐢ㄤ箣鍓嶅缓濂界殑 `icu_agent` 搴擄級锛?

```bash
export ICU_PG_DSN="dbname=icu_agent user=<浣犵殑绯荤粺鐢ㄦ埛鍚? host=localhost port=5432"
```

濡傛灉涓嶈缃紝浼氫娇鐢ㄩ粯璁わ細

```text
dbname=icu_agent user=zhou host=localhost port=5432
```

### 1.3 鍚姩鏈嶅姟

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- 鏂囨。锛圫wagger锛夛細`http://127.0.0.1:8000/docs`
- 鍋ュ悍妫€鏌ワ細`GET /health`
- 鏁版嵁搴撳仴搴锋鏌ワ細`GET /api/v1/ops/db-health`

### 1.4 璺ㄧ數鑴戣皟鐢紙鍓嶇鍦ㄥ叾浠栨満鍣級

1. 鍚庣鏈哄櫒鍚姩 API 鍚庯紝鏌ユ湰鏈哄眬鍩熺綉 IP锛堜緥濡?`192.168.1.20`锛夈€?
2. 纭繚闃茬伀澧欐斁琛?TCP `8000` 绔彛銆?
3. 鍓嶇鎶?baseURL 閰嶆垚锛?

```text
http://<backend-lan-ip>:8000
```

4. CORS 閫氳繃鐜鍙橀噺閰嶇疆锛?

```bash
# 寮€鍙戞湡锛堝厑璁告墍鏈夋簮锛?
ICU_CORS_ORIGINS=*

# 寤鸿锛氳仈璋?鐢熶骇鏈燂紙鍙厑璁告寚瀹氬墠绔級
ICU_CORS_ORIGINS=http://192.168.1.30:5173,https://your-frontend.example.com
```

---

## 2. API 鎬昏

鎵€鏈変笟鍔¤矾鐢卞墠缂€涓猴細`/api/v1`

### 2.1 鍐欏叆绫伙紙浜嬩欢椹卞姩锛?

杩欎笁绫绘槸**鍞竴鐨勫啓鍏ュ叆鍙?*锛屽悗绔唴閮ㄤ細瀹屾垚锛?

> 鏍￠獙 admission 瀛樺湪涓?active 鈫?鍐欐槑缁嗚〃  
> 鈫?鍐?`events` 鈫?UPSERT `patient_state_current` 鈫?鍐?`audit_logs`

- `POST /api/v1/admissions/{admission_id}/events/vital_sign`
  - 浣滅敤锛氬啓鍏ヤ竴鏉＄敓鍛戒綋寰佷簨浠讹紙瀵归綈 APACHE 瀛楁锛?
  - 璇锋眰浣擄細`VitalSignEventCreate`
  - 杩斿洖锛歚EventWriteResult`

- `POST /api/v1/admissions/{admission_id}/events/lab`
  - 浣滅敤锛氬啓鍏ュ寲楠?妫€楠岀粨鏋?
  - 璇锋眰浣擄細`LabEventCreate`
  - 杩斿洖锛歚EventWriteResult`

- `POST /api/v1/admissions/{admission_id}/events/intervention`
  - 浣滅敤锛氬啓鍏ユ不鐤?骞查浜嬩欢
  - 璇锋眰浣擄細`InterventionEventCreate`
  - 杩斿洖锛歚EventWriteResult`

### 2.2 鐘舵€佷笌椋庨櫓/鍛婅鏌ヨ

- `GET /api/v1/admissions/{admission_id}/state/current`
  - 璇诲彇褰撳墠鑱氬悎鐘舵€侊紙`patient_state_current`锛?
  - 杩斿洖锛歚PatientStateCurrentOut`

- `GET /api/v1/admissions/{admission_id}/alerts`
  - 璇诲彇鍛婅鍒楄〃锛坄alerts`锛?
  - 杩斿洖锛歚AlertOut[]`

- `GET /api/v1/admissions/{admission_id}/risks`
  - 璇诲彇椋庨櫓璇勪及缁撴灉锛坄risk_assessments`锛?
  - 杩斿洖锛歚RiskAssessmentOut[]`

### 2.3 Agent 浜や簰鎬荤嚎锛堜竴鏈熸柊澧烇級

- `GET /api/v1/admissions/{admission_id}/agent_outputs?agent_name=...&limit=...`
  - 璇诲彇鎸囧畾搴婁綅鐨?agent 缁撴瀯鍖栬緭鍑猴紙`agent_outputs`锛?
- `GET /api/v1/admissions/{admission_id}/agent_events?producer_agent=...&limit=...`
  - 璇诲彇 agent 浜嬩欢娴侊紙`agent_events`锛?
- `GET /api/v1/admissions/{admission_id}/agent_cursors`
  - 璇诲彇涓婂眰 agent 娑堣垂娓告爣锛坄agent_consumption_cursor`锛?
- `POST /agents/bedside-monitor/analyze`
  - 鐢熸垚 bedside 杈撳嚭骞跺彂甯?`bedside_analysis_ready` 浜嬩欢
- `POST /agents/intervention-tracker/evaluate`
  - 鐢熸垚骞查璇勪及骞跺彂甯?`intervention_evaluation_ready` 浜嬩欢
- `POST /agents/risk-sentinel/evaluate`
  - 璇诲彇涓婃父鏂颁簨浠讹紙鎸?cursor 澧為噺锛夊悗鍐欏叆 `risk_assessments`銆乣alerts`锛屽苟鍙戝竷 `risk_assessment_ready`

### 2.4 涓绘暟鎹笌鏄庣粏鍘嗗彶

- 涓绘暟鎹細
  - `GET /api/v1/patients/{patient_id}` 鈫?`PatientOut`
  - `GET /api/v1/beds/{bed_id}` 鈫?`BedOut`
  - `GET /api/v1/admissions/{admission_id}` 鈫?`AdmissionOut`

- 浜嬩欢涓庢槑缁嗭細
  - `GET /api/v1/admissions/{admission_id}/events?limit=50` 鈫?`EventOut[]`
  - `GET /api/v1/admissions/{admission_id}/vitals?limit=100` 鈫?`VitalSignEventOut[]`
  - `GET /api/v1/admissions/{admission_id}/labs?limit=100` 鈫?`LabEventOut[]`
  - `GET /api/v1/admissions/{admission_id}/interventions?limit=100` 鈫?`InterventionEventOut[]`

- 鐘舵€佸揩鐓т笌瀹¤锛?
  - `GET /api/v1/admissions/{admission_id}/snapshots?limit=50` 鈫?`PatientStateSnapshotOut[]`
  - `GET /api/v1/admissions/{admission_id}/audit_logs?limit=100` 鈫?`AuditLogOut[]`

> `limit` 鍙傛暟閮芥湁涓婇檺锛堜緥濡?200/500锛夛紝闃叉涓€娆℃€ф媺澶璁板綍銆?

---

## 3. 鍏稿瀷璋冪敤绀轰緥

### 3.1 鐢?curl 涓婁紶鐢熷懡浣撳緛

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/admissions/ICU-ADM-0001/events/vital_sign" \
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

杩斿洖锛堢ず渚嬶級锛?

```json
{
  "event_id": "evt_xxx",
  "detail_id": "vital_xxx",
  "admission_id": "ICU-ADM-0001",
  "patient_id": "p1",
  "bed_id": "b1"
}
```

### 3.2 鐢?curl 鏌ヨ褰撳墠鐘舵€?

```bash
curl "http://127.0.0.1:8000/api/v1/admissions/ICU-ADM-0001/state/current"
```

杩斿洖鍏抽敭瀛楁锛堢畝鍖栵級锛?

```json
{
  "admission_id": "ICU-ADM-0001",
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

### 3.3 鐢?Python锛堢粰 agent / 鍓嶇鍚庣鑴氭湰锛?

```python
import requests
from datetime import datetime, timezone

BASE = "http://127.0.0.1:8000"

# 鍋ュ悍妫€鏌?
print(requests.get(f"{BASE}/health").json())

# 涓婁紶涓€鏉＄敓鍛戒綋寰?
ts = datetime.now(timezone.utc).isoformat()
resp = requests.post(
    f"{BASE}/api/v1/admissions/ICU-ADM-0001/events/vital_sign",
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

# 鏌ヨ褰撳墠鐘舵€?
state = requests.get(f"{BASE}/api/v1/admissions/ICU-ADM-0001/state/current").json()
print("care_phase:", state["care_phase"])
print("vitals:", state["current_vitals"])
```

### 3.4 瑙﹀彂 3 涓牳蹇?agent锛堟渶灏忛棴鐜級

```bash
# 1) bedside_monitor 鍙戝竷杈撳嚭/浜嬩欢
curl -X POST "http://127.0.0.1:8000/agents/bedside-monitor/analyze" \
  -H "Content-Type: application/json" \
  -d '{
    "admission_id":"ICU-ADM-0001",
    "analysis_window":"last_4h"
  }'

# 2) intervention_tracker 鍙戝竷杈撳嚭/浜嬩欢
curl -X POST "http://127.0.0.1:8000/agents/intervention-tracker/evaluate" \
  -H "Content-Type: application/json" \
  -d '{
    "admission_id":"ICU-ADM-0001",
    "intervention_id":"INT-20260508-10002"
  }'

# 3) risk_sentinel 鎸?cursor 澧為噺娑堣垂涓婃父浜嬩欢骞惰惤搴?
curl -X POST "http://127.0.0.1:8000/agents/risk-sentinel/evaluate" \
  -H "Content-Type: application/json" \
  -d '{
    "admission_id":"ICU-ADM-0001",
    "max_events":200
  }'
```

### 3.5 鏌ヨ agent 鎬荤嚎鐘舵€?

```bash
curl "http://127.0.0.1:8000/api/v1/admissions/ICU-ADM-0001/agent_outputs?limit=20"
curl "http://127.0.0.1:8000/api/v1/admissions/ICU-ADM-0001/agent_events?limit=20"
curl "http://127.0.0.1:8000/api/v1/admissions/ICU-ADM-0001/agent_cursors"
```

---

## 4. Agent 浜や簰濂戠害锛堟柊澧烇級

### 4.1 浣曟椂鍐?PostgreSQL

- `bedside_monitor`锛氭瘡娆″垎鏋愮粨鏉熷啓 `agent_outputs` + `agent_events`
- `intervention_tracker`锛氭瘡娆¤瘎浼扮粨鏉熷啓 `agent_outputs` + `agent_events`
- `risk_sentinel`锛氭秷璐逛笂娓告柊浜嬩欢鍚庡啓 `risk_assessments`銆乣alerts`锛屽苟鍐欒嚜宸辩殑 `agent_outputs` + `agent_events`

### 4.2 涓婂眰 agent 濡備綍鐭ラ亾鏈夋柊鏁版嵁

- 姣忎釜涓婂眰 agent 鍦?`agent_consumption_cursor` 缁存姢 `(consumer_agent, admission_id)` 鐨?`last_event_at`
- 娑堣垂鏃跺彧璇诲彇 `produced_at > last_event_at` 鐨勪笂娓镐簨浠?
- 鎴愬姛澶勭悊鍚庢彁浜?cursor锛屼繚璇佸箓绛夊拰鏂偣缁窇

### 4.3 鏂?agent 鎺ュ叆瑙勮寖

- 鍦?`agent_registry` 娉ㄥ唽锛?
  - `agent_name`
  - `input_event_types`
  - `output_event_type`
  - `schema_version`
- 鏂?agent 鍙閬靛惊璇ュ绾﹀嵆鍙帴鍏ワ紝涓嶉渶瑕佹敼鏃?agent 浠ｇ爜

## 5. 缁欎笉鍚岃鑹茬殑浣跨敤寤鸿

### 4.1 鏃跺簭妯℃嫙鍣紙鏁版嵁鐢熸垚绔級

- **鍙皟鐢ㄥ啓鍏ユ帴鍙?*锛?
  - `POST /events/vital_sign`
  - `POST /events/lab`
  - `POST /events/intervention`
- 涓嶇洿鎺ユ搷浣滄暟鎹簱锛屼笉鐩存帴鍐?`patient_state_current` / `alerts` / `risk_assessments`銆?

### 4.2 Agent 灞?

- **鍏稿瀷璇诲彇鍏ュ彛**锛?
  - 浠ュ崟搴婁綅锛坅dmission锛変负鍗曚綅锛?
    - `GET /admissions/{admission_id}/state/current`
    - `GET /admissions/{admission_id}/vitals` / `labs` / `interventions`
    - `GET /admissions/{admission_id}/risks` / `alerts`
    - 濡傞渶鐥呯▼鍥炴斁 鈫?`GET /admissions/{admission_id}/events` + `snapshots` + `audit_logs`
- 濡傛棤蹇呰锛?*涓嶈鍐欏叆**锛岃€屾槸鎶婃帹鐞嗙粨鏋滆繑鍥炵粰 orchestrator锛屽悗鑰呭啀鍐冲畾鏄惁鍐?`risk_assessments` / `alerts`锛堜箣鍚庡彲浠ユ墿灞曚笓闂ㄧ殑鍐欐帴鍙ｏ級銆?

### 4.3 鍓嶇 / 鍙鍖?

- ICU 鎬昏锛?
  - 褰撳墠鍙互閫氳繃 `admissions` + `patient_state_current` + `alerts` 鑱氬悎锛涚幇闃舵 API 鎸?admission 鏆撮湶锛屽悗缁彲澧炲姞鎴块棿/搴婁綅绾ц仛鍚堟帴鍙ｃ€?
- 鍗曞簥浣嶈鎯咃細
  - 褰撳墠鐘舵€侊細`/state/current`
  - 鏃堕棿绾匡細`/events` + 鍚勭被鏄庣粏 `/vitals` `/labs` `/interventions`
  - 鍛婅闈㈡澘锛歚/alerts`
  - 椋庨櫓鍗＄墖锛歚/risks`

---

## 6. 鐗堟湰涓庢紨杩?

- 褰撳墠 API 鐗堟湰锛歚v1`锛堝墠缂€ `/api/v1`锛?
- 鏈潵濡傞渶瀵?schema 鍋氫笉鍏煎淇敼锛屽缓璁鍔?`/api/v2` 鍓嶇紑锛屼繚鎸佹棫鐗堟湰鍙敤涓€娈垫椂闂淬€?

鏇村簳灞傜殑鏁版嵁瀛楁瀹氫箟涓庤〃缁撴瀯锛岃濮嬬粓浠ワ細

- `../鏁版嵁瑙勮寖/鏁版嵁绫诲瀷.md`
- `../鏁版嵁瑙勮寖/鏁版嵁搴撲娇鐢ㄨ鑼?md`

涓哄噯銆?** End Patch***}"/>

## 7. 完整 Demo 闭环（新增）

### 7.1 一键触发单患者闭环

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/orchestrator/demo-run" \
  -H "Content-Type: application/json" \
  -d '{
    "admission_id": "ICU-ADM-0001",
    "memory_window_hours": 24,
    "top_k": 10
  }'
```

### 7.2 一键触发全活跃患者闭环（动态纳入新患者）

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/orchestrator/demo-run" \
  -H "Content-Type: application/json" \
  -d '{
    "run_all_active": true,
    "memory_window_hours": 24,
    "top_k": 10
  }'
```

### 7.3 查询 pipeline 回放日志

```bash
curl "http://127.0.0.1:8000/api/v1/orchestrator/runs?limit=20"
curl "http://127.0.0.1:8000/api/v1/orchestrator/runs/<run_id>"
```

说明：orchestrator 运行会把每一步状态、耗时、摘要写入 `orchestrator_runs`，并同步写审计 `audit_logs`。
