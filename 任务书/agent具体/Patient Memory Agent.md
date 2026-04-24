# Patient Memory Agent（单患者）设计

## 1. Agent 定位

**Patient Memory Agent** 是每个患者的“病程记忆体”。

它不做实时监测，也不直接做风险判断，而是负责把分散的数据和 agent 输出整理成连续的患者病程上下文。

它回答的问题是：

> 这个患者从入 ICU 到现在，发生了什么？当前最重要的问题是什么？哪些变化是新的，哪些是反复出现的？哪些治疗有效，哪些治疗效果有限？

它是后续 **Risk Sentinel、Clinical Summary、Compassion Agent** 的核心输入来源。

---

# 2. 输入来源

Patient Memory 接收四类信息。

## 2.1 Bedside Monitor 输出

例如：

```json
{
  "event_type": "vital_summary",
  "summary": "过去30分钟 MAP 持续低于65，伴心率升高。",
  "abnormal_flags": ["persistent_hypotension", "tachycardia"],
  "trend_labels": ["MAP_downtrend"],
  "urgency_level": "warning"
}
```

## 2.2 Intervention Tracker 输出

例如：

```json
{
  "event_type": "intervention_response",
  "intervention_type": "fluid_bolus",
  "response_label": "partially_responsive",
  "summary": "补液后 MAP 有轻度改善，但仍低于目标。",
  "concern_flags": ["persistent_hypotension_after_fluid"]
}
```

## 2.3 实验室 / 检查结果

例如：

```json
{
  "event_type": "lab_update",
  "lab_name": "lactate",
  "value": 3.8,
  "unit": "mmol/L",
  "trend": "increasing"
}
```

## 2.4 人工录入病程事件

例如：

```json
{
  "event_type": "clinical_note",
  "summary": "患者因感染性休克收入 ICU，目前使用去甲肾上腺素维持血压。"
}
```

---

# 3. 核心输出

Patient Memory 输出三层记忆。

## 3.1 短期记忆：最近 1–6 小时

关注即时变化：

```json
{
  "short_term_memory": {
    "time_window": "last_6h",
    "key_events": [
      "MAP 持续低于目标",
      "13:30 补液500ml后仅部分反应",
      "去甲肾上腺素需求增加"
    ],
    "current_unstable_features": [
      "persistent_hypotension",
      "increasing_vasopressor_requirement"
    ]
  }
}
```

## 3.2 中期记忆：最近 24 小时

关注病情走势：

```json
{
  "mid_term_memory": {
    "time_window": "last_24h",
    "major_changes": [
      "循环状态较昨日更不稳定",
      "乳酸较前次升高",
      "补液反应有限"
    ],
    "unresolved_problems": [
      "shock_not_resolved",
      "possible_infection_progression"
    ]
  }
}
```

## 3.3 长期记忆：入 ICU 以来

关注病程主线：

```json
{
  "long_term_memory": {
    "icu_course_summary": "患者因感染性休克收入 ICU，入科后持续需要升压药支持。过去24小时循环不稳定加重，补液反应有限。",
    "baseline_context": [
      "admitted_for_septic_shock",
      "mechanically_ventilated",
      "on_vasopressor_support"
    ],
    "known_response_patterns": [
      "fluid_response_limited",
      "vasopressor_response_present_but_requirement_increasing"
    ]
  }
}
```

---

# 4. Agent 工作流程

## Step 1：接收更新事件

Patient Memory 不主动频繁运行，而是被事件触发。

触发来源：

```text
Bedside Monitor 完成状态摘要
Intervention Tracker 完成干预反应评估
Lab result 更新
Clinical note 更新
查房时间到达
```

---

## Step 2：判断事件重要性

不是所有数据都进入 memory summary。

需要进入记忆的事件包括：

```text
新的异常趋势
持续存在的异常
治疗后无效或恶化
关键实验室指标恶化
新的诊断 / 新的主要问题
重大治疗变化
风险级别上升
```

普通波动可以只保存在数据库，不进入语义记忆。

---

## Step 3：更新短期记忆

短期记忆用于回答：

```text
最近几小时发生了什么？
患者现在为什么需要关注？
最新异常是否已经处理？
```

例如：

```text
过去6小时内，患者出现持续低血压。13:30补液后MAP仅轻度上升但仍未达标，提示循环状态仍不稳定。
```

---

## Step 4：更新中期记忆

中期记忆用于回答：

```text
今天整体是好转还是恶化？
主要问题有没有解决？
哪些干预有效？
```

例如：

```text
过去24小时循环支持需求增加，补液反应有限，乳酸上升，提示休克状态仍未缓解。
```

---

## Step 5：更新长期病程主线

长期记忆用于形成稳定背景：

```text
入 ICU 原因
主要诊断背景
关键转折点
治疗反应模式
长期未解决问题
```

例如：

```text
患者入 ICU 后主要问题为感染性休克和呼吸衰竭。早期对补液有一定反应，但近24小时补液反应减弱，升压药需求增加。
```

---

# 5. 数据库设计

## 5.1 patient_memory 表

```sql
CREATE TABLE patient_memory (
    memory_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    bed_id TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL,

    short_term_summary TEXT,
    mid_term_summary TEXT,
    long_term_summary TEXT,

    active_problems JSONB,
    unresolved_issues JSONB,
    key_events JSONB,
    response_patterns JSONB,

    source_event_ids JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 5.2 patient_memory_events 表

记录进入 memory 的关键事件。

```sql
CREATE TABLE patient_memory_events (
    memory_event_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    bed_id TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL,

    source_agent TEXT,
    event_type TEXT,
    event_summary TEXT,
    importance_level TEXT,

    related_intervention_id TEXT,
    related_vital_event_id TEXT,
    evidence JSONB,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

# 6. 记忆更新规则

## 6.1 哪些事件进入短期记忆

```text
urgency_level = warning 或 critical
新的 abnormal_flag 出现
同一 abnormal_flag 持续超过一定时间
intervention response 为 non_responsive
intervention response 为 deteriorating_despite_intervention
关键 lab 明显恶化
```

## 6.2 哪些事件进入中期记忆

```text
过去24小时内重复出现的问题
治疗反应模式发生变化
风险级别持续升高
同一 unresolved issue 多次出现
多个 agent 指向同一个问题
```

## 6.3 哪些事件进入长期记忆

```text
入 ICU 原因
主要诊断背景
重大病情转折
插管 / 拔管 / 升压药启动
明确的治疗反应模式
长期未解决问题
```

---

# 7. 输出给其他 agent 的格式

## 7.1 给 Risk Sentinel

```json
{
  "patient_id": "P001",
  "memory_context": {
    "current_main_problem": "persistent shock",
    "recent_trajectory": "worsening over last 6h",
    "known_response_pattern": "limited response to fluid bolus",
    "unresolved_issues": [
      "persistent_hypotension",
      "rising_lactate"
    ]
  }
}
```

## 7.2 给 Clinical Summary

```json
{
  "patient_id": "P001",
  "round_memory": {
    "icu_course_summary": "患者因感染性休克收入 ICU，目前仍需升压药支持。",
    "last_24h_key_events": [
      "循环状态不稳定",
      "补液反应有限",
      "乳酸升高"
    ],
    "active_problem_list": [
      "shock",
      "possible infection progression",
      "respiratory failure"
    ]
  }
}
```

## 7.3 给 Compassion Agent

```json
{
  "patient_id": "P001",
  "family_communication_context": {
    "plain_language_summary_basis": "患者目前主要问题是血压不稳定和感染控制仍需观察。",
    "major_change_since_last_update": "今天血压支持需求增加。",
    "communication_sensitivity": "condition_worsened"
  }
}
```

---

# 8. 和其他 agent 的边界

| Agent                | 职责           |
| -------------------- | ------------ |
| Bedside Monitor      | 发现当前生命体征异常   |
| Intervention Tracker | 判断治疗前后反应     |
| Patient Memory       | 整理病程上下文和长期模式 |
| Risk Sentinel        | 基于上下文评估风险    |
| Clinical Summary     | 生成医生可读摘要     |
| Compassion Agent     | 转成家属可理解语言    |

Patient Memory 不应该说：

```text
建议立即增加升压药
建议插管
诊断为脓毒性休克
```

它应该说：

```text
过去6小时低血压持续存在，补液后反应有限，升压药需求增加。
```

---

# 9. 推荐 Agent Prompt

```text
You are the Patient Memory Agent for a single ICU patient.

Your task is to maintain a structured, time-aware memory of the patient's ICU course. You do not make treatment decisions, diagnoses, or medical orders. You summarize clinically relevant events into short-term, mid-term, and long-term memory.

Inputs:
1. Bedside Monitor summaries.
2. Intervention Tracker assessments.
3. Lab updates.
4. Clinical notes.
5. Existing patient memory.

Process:
1. Decide whether the new event is clinically important enough to update memory.
2. Update short-term memory for recent 1–6 hour changes.
3. Update mid-term memory for 24-hour trajectory.
4. Update long-term memory for ICU course, major turning points, and known response patterns.
5. Maintain active problems, unresolved issues, and key event timeline.
6. Return structured JSON only.

Rules:
- Do not recommend new treatments.
- Do not produce final diagnoses.
- Do not overwrite important historical context unless clearly superseded.
- Distinguish new events from repeated or persistent problems.
- Always include source events and time windows.
```

---

# 10. 最小可实现版本

第一版只需要维护 5 个字段：

```json
{
  "patient_id": "P001",
  "short_term_summary": "...",
  "mid_term_summary": "...",
  "long_term_summary": "...",
  "active_problems": [],
  "unresolved_issues": []
}
```

