# Ward Coordinator Agent 设计

## 1. Agent 定位

**Ward Coordinator Agent** 是 ICU 病房级协调 agent。

它不是单患者 agent，而是面向 **20 张 ICU 床位整体** 的全局调度 agent。

它回答的问题是：

> 当前整个 ICU 中，哪些患者最需要优先关注？哪些告警需要合并？医护注意力应该如何排序？

---

# 2. 核心职责

Ward Coordinator 主要做 6 件事：

```text
1. 汇总所有床位的风险状态
2. 对患者进行优先级排序
3. 合并重复告警，避免告警风暴
4. 识别新近恶化患者
5. 生成 ICU 全局关注列表
6. 为 Clinical Summary / Dashboard 提供全病房视图
```

---

# 3. 输入来源

它主要读取每张床的：

```text
Risk Sentinel 输出
Clinical Summary 输出
Patient Memory 当前 unresolved issues
Bedside Monitor 最新 urgency
Intervention Tracker 最新 response_label
出入院状态 / 床位状态
```

输入示例：

```json
{
  "bed_id": "B07",
  "patient_id": "P001",
  "risk_sentinel": {
    "overall_risk_level": "high",
    "active_risks": ["persistent_shock_risk"],
    "trajectory": "worsening"
  },
  "clinical_summary": {
    "one_line_status": "Hemodynamically unstable with limited fluid response."
  },
  "latest_intervention_response": "partially_responsive",
  "bed_status": "occupied"
}
```

---

# 4. 输出格式

```json
{
  "agent": "ward_coordinator",
  "timestamp": "2026-04-24T16:00:00",
  "icu_status": {
    "occupied_beds": 18,
    "critical_patients": 2,
    "high_risk_patients": 5,
    "new_deteriorations": 3
  },
  "priority_queue": [
    {
      "rank": 1,
      "bed_id": "B07",
      "patient_id": "P001",
      "priority_level": "urgent",
      "reason": [
        "high persistent_shock_risk",
        "worsening trajectory",
        "limited response to recent intervention"
      ],
      "suggested_attention": "urgent human review"
    }
  ],
  "merged_alerts": [
    {
      "alert_group": "shock_related_alerts",
      "beds": ["B07", "B12"],
      "count": 2
    }
  ],
  "ward_summary": "ICU currently has 2 critical patients and 5 high-risk patients. Bed 07 is the top priority due to worsening shock-related risk."
}
```

---

# 5. 优先级排序逻辑

建议使用简单 scoring。

## 5.1 基础分

```text
Risk level:
low = 1
moderate = 2
high = 4
critical = 6
```

## 5.2 加权项

```text
trajectory worsening: +2
new deterioration within 1h: +2
deteriorating_despite_intervention: +3
non_responsive intervention: +2
multiple active risks: +1 per additional risk
unresolved critical issue: +2
recent repeated alert: +1
```

## 5.3 优先级映射

```text
0–2: routine
3–5: watch
6–8: urgent
>=9: immediate
```

---

# 6. 告警合并逻辑

Ward Coordinator 必须避免“告警风暴”。

## 6.1 同一患者告警合并

例如 Bed 07 同时出现：

```text
persistent_hypotension
rising_lactate
fluid_non_responsive
high_shock_risk
```

不要显示 4 条独立告警，而是合并为：

```text
Bed 07: worsening shock-related risk
```

## 6.2 同类跨床位告警合并

例如多个患者有 shock risk：

```json
{
  "alert_group": "shock_related_alerts",
  "beds": ["B07", "B12", "B16"],
  "count": 3
}
```

---

# 7. 运行时机

## 定时运行

```text
每 5–15 分钟刷新 ICU 全局队列
每次查房前生成 round priority list
每班交班前生成 shift handoff list
```

## 事件触发

```text
Risk Sentinel 输出 high / critical
某患者出现 new deterioration
Intervention Tracker 输出 deteriorating_despite_intervention
新患者入 ICU
患者转出 / 出院
```

---

# 8. 数据库设计

## ward_priority_snapshots 表

```sql
CREATE TABLE ward_priority_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    generated_at TIMESTAMP NOT NULL,

    occupied_beds INT,
    critical_patients INT,
    high_risk_patients INT,
    new_deteriorations INT,

    priority_queue JSONB,
    merged_alerts JSONB,
    ward_summary TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## ward_priority_events 表

```sql
CREATE TABLE ward_priority_events (
    event_id TEXT PRIMARY KEY,
    generated_at TIMESTAMP NOT NULL,

    bed_id TEXT,
    patient_id TEXT,
    priority_level TEXT,
    priority_score INT,
    reasons JSONB,
    source_risk_ids JSONB,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

# 9. 和其他 agent 的交互

## 输入边

```text
Risk Sentinel → Ward Coordinator
Clinical Summary → Ward Coordinator
Patient Memory → Ward Coordinator
Intervention Tracker → Ward Coordinator
Bedside Monitor → Ward Coordinator
```

## 输出边

```text
Ward Coordinator → Clinical Summary
Ward Coordinator → Compassion Agent
Ward Coordinator → Frontend Dashboard
Ward Coordinator → Audit Log
```

---

# 10. 与其他 agent 的边界

| Agent            | 作用           |
| ---------------- | ------------ |
| Risk Sentinel    | 判断单患者风险      |
| Clinical Summary | 生成单患者医护摘要    |
| Patient Memory   | 提供单患者病程上下文   |
| Ward Coordinator | 做全 ICU 优先级排序 |
| Compassion Agent | 处理家属沟通与人文表达  |

Ward Coordinator 不应该说：

```text
给 Bed 07 增加升压药
立即调整呼吸机参数
```

它应该说：

```text
Bed 07 因高休克风险、恶化趋势和干预反应有限，当前排在优先关注队列第1位。
```

---

# 11. 推荐 Agent Prompt

```text
You are the Ward Coordinator Agent for a 20-bed ICU simulation system.

Your task is to coordinate attention across all ICU beds. You do not make diagnoses, prescribe treatment, or issue medical orders. You rank patients by urgency, merge alerts, identify new deteriorations, and generate a ward-level priority overview.

Inputs:
1. Risk Sentinel outputs from all occupied beds.
2. Clinical Summary outputs from all occupied beds.
3. Patient Memory unresolved issues.
4. Bedside Monitor urgency signals.
5. Intervention Tracker response assessments.
6. Bed admission, discharge, and occupancy status.

Process:
1. Filter occupied beds.
2. Collect current risk level and trajectory for each patient.
3. Compute a priority score.
4. Merge repeated or related alerts.
5. Identify new deterioration cases.
6. Generate a ranked priority queue.
7. Return structured JSON only.

Rules:
- Do not make treatment decisions.
- Do not override single-patient evidence.
- Prioritize patients with worsening trajectory or poor response after intervention.
- Merge duplicate alerts into clinically meaningful groups.
- Always include reasons for ranking.
```

---

# 12. 最小可实现版本

第一版只需要输出：

```json
{
  "icu_status": {
    "occupied_beds": 20,
    "critical_patients": 1,
    "high_risk_patients": 4
  },
  "priority_queue": [
    {
      "rank": 1,
      "bed_id": "B07",
      "patient_id": "P001",
      "priority_level": "urgent",
      "reason": [
        "high shock risk",
        "worsening trajectory",
        "limited intervention response"
      ]
    }
  ],
  "ward_summary": "Bed 07 is currently the highest priority patient."
}
```

