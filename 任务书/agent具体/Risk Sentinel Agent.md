# Risk Sentinel Agent（单患者）设计

## 1. Agent 定位

**Risk Sentinel Agent** 是单患者的风险预警 agent。

它不负责实时采集数据，也不直接给治疗方案，而是整合：

```text
Bedside Monitor：当前生命体征异常
Intervention Tracker：治疗后反应
Patient Memory：病程上下文
Labs / Notes：实验室和病程信息
```

然后回答：

> 这个患者现在有哪些临床风险？风险是否正在上升？是否需要提升关注优先级？

---

# 2. 核心职责

Risk Sentinel 主要做 5 件事：

```text
1. 识别当前活跃风险
2. 判断风险等级
3. 解释风险依据
4. 识别是否存在“恶化趋势”
5. 决定是否需要通知 Ward Coordinator / Clinical Summary
```

它输出的是 **risk profile**，不是诊断结论。

例如它可以说：

```text
存在持续性休克风险升高信号。
```

但不应该说：

```text
患者确诊为感染性休克，需要立即增加去甲肾上腺素。
```

---

# 3. 输入数据

## 3.1 Bedside Monitor 输入

```json
{
  "patient_id": "P001",
  "abnormal_flags": [
    "persistent_hypotension",
    "tachycardia"
  ],
  "trend_labels": [
    "MAP_downtrend",
    "HR_uptrend"
  ],
  "urgency_level": "warning",
  "summary": "过去30分钟 MAP 持续低于65，HR升高。"
}
```

## 3.2 Intervention Tracker 输入

```json
{
  "patient_id": "P001",
  "intervention_type": "fluid_bolus",
  "response_label": "partially_responsive",
  "concern_flags": [
    "persistent_hypotension_after_fluid"
  ],
  "summary": "补液后 MAP 有轻度改善，但仍低于目标。"
}
```

## 3.3 Patient Memory 输入

```json
{
  "patient_id": "P001",
  "memory_context": {
    "recent_trajectory": "worsening over last 6h",
    "known_response_pattern": "limited response to fluid bolus",
    "unresolved_issues": [
      "persistent_hypotension",
      "rising_lactate"
    ],
    "current_main_problem": "persistent shock"
  }
}
```

## 3.4 Labs 输入

```json
{
  "patient_id": "P001",
  "labs": [
    {
      "name": "lactate",
      "value": 4.2,
      "unit": "mmol/L",
      "trend": "increasing",
      "timestamp": "2026-04-24T14:00:00"
    }
  ]
}
```

---

# 4. 输出格式

Risk Sentinel 的输出建议固定为：

```json
{
  "patient_id": "P001",
  "bed_id": "B07",
  "agent": "risk_sentinel",
  "timestamp": "2026-04-24T14:10:00",
  "overall_risk_level": "high",
  "active_risks": [
    {
      "risk_type": "persistent_shock_risk",
      "risk_level": "high",
      "confidence": "medium_high",
      "evidence": [
        "MAP remained below target over the recent window",
        "Fluid bolus was followed by only partial response",
        "Lactate is increasing",
        "Patient memory indicates worsening trajectory over last 6h"
      ],
      "time_window": "last_6h",
      "trajectory": "worsening",
      "escalation_level": "urgent_review"
    }
  ],
  "new_or_worsening_flags": [
    "shock_risk_worsening"
  ],
  "recommended_next_attention": [
    "Review hemodynamic status",
    "Check whether shock-related issue remains unresolved"
  ],
  "notify_agents": [
    "ward_coordinator",
    "clinical_summary",
    "patient_memory"
  ]
}
```

注意：`recommended_next_attention` 是“需要关注什么”，不是“做什么治疗”。

---

# 5. 风险类型设计

第一版建议支持 6 类风险。

```text
1. persistent_shock_risk
2. respiratory_failure_risk
3. sepsis_worsening_risk
4. aki_risk
5. oversedation_or_delirium_risk
6. post_intervention_deterioration_risk
```

## 5.1 persistent_shock_risk

主要证据：

```text
persistent_hypotension
MAP_downtrend
tachycardia
rising_lactate
increasing_vasopressor_requirement
fluid_non_responsive / partially_responsive
```

## 5.2 respiratory_failure_risk

主要证据：

```text
persistent_hypoxemia
SpO2_downtrend
RR_uptrend
increasing_FiO2_requirement
high_airway_pressure
ventilator_adjustment_non_responsive
abnormal_ABG
```

## 5.3 sepsis_worsening_risk

主要证据：

```text
fever_persistent
WBC_abnormal_or_worsening
rising_lactate
hypotension
increasing_vasopressor_requirement
antibiotic_response_non_responsive after delayed window
```

## 5.4 aki_risk

主要证据：

```text
low_urine_output
creatinine_rising
hypotension
diuretic_non_responsive
positive_fluid_balance if available
```

## 5.5 oversedation_or_delirium_risk

主要证据：

```text
RASS too low / too high
sedation_adjustment_non_responsive
RR suppression
ventilator asynchrony
agitation events
```

## 5.6 post_intervention_deterioration_risk

主要证据：

```text
deteriorating_despite_intervention
repeated_non_responsive_interventions
worsening_after_treatment_change
```

---

# 6. 风险等级

建议统一使用 4 级：

```text
low
moderate
high
critical
```

## 6.1 low

```text
存在轻微异常，但没有持续趋势，也没有治疗失败证据。
```

## 6.2 moderate

```text
存在持续异常或早期恶化趋势，但暂未出现多指标恶化。
```

## 6.3 high

```text
存在多指标异常，或异常持续存在，并且治疗反应有限。
```

## 6.4 critical

```text
干预后仍恶化，或多个系统同时恶化，或出现严重低氧/严重低血压等强风险信号。
```

---

# 7. 核心判断逻辑

Risk Sentinel 的关键不是单个阈值，而是多来源证据叠加。

可以设计一个简单 risk scoring。

## 7.1 证据加分规则

```text
Bedside Monitor warning flag: +1
Bedside Monitor critical flag: +2

abnormal trend worsening: +1
persistent abnormality: +1

Intervention partially_responsive: +1
Intervention non_responsive: +2
Intervention deteriorating_despite_intervention: +3

Patient Memory says worsening trajectory: +2
Patient Memory says unresolved issue repeated: +1

Lab mildly abnormal: +1
Lab worsening trend: +2
```

## 7.2 分数映射

```text
0–1: low
2–3: moderate
4–6: high
>=7: critical
```

---

# 8. 示例规则

## 8.1 休克风险规则

```text
如果 persistent_hypotension + rising_lactate:
    至少 high

如果 persistent_hypotension + vasopressor_requirement_increasing:
    至少 high

如果 fluid_bolus 后 non_responsive 或 deteriorating:
    high / critical

如果 MAP 继续下降 + lactate 上升 + 治疗后无效:
    critical
```

输出示例：

```json
{
  "risk_type": "persistent_shock_risk",
  "risk_level": "high",
  "confidence": "medium_high",
  "evidence": [
    "MAP remained below target",
    "Fluid response was limited",
    "Lactate trend is increasing"
  ],
  "trajectory": "worsening",
  "escalation_level": "urgent_review"
}
```

---

## 8.2 呼吸衰竭风险规则

```text
如果 SpO2 持续 < 90:
    至少 high

如果 SpO2 下降 + FiO2 需求增加:
    high

如果 ventilator adjustment 后 SpO2 无改善:
    high

如果 SpO2 持续下降 + peak pressure 升高:
    critical
```

---

## 8.3 AKI 风险规则

```text
如果尿量持续下降:
    moderate

如果尿量下降 + creatinine 上升:
    high

如果低血压持续 + 尿量下降:
    high

如果补液/利尿后尿量仍无改善:
    high
```

---

# 9. 运行时机

Risk Sentinel 不需要每秒运行，而应该在以下情况触发。

## 9.1 被动触发

```text
Bedside Monitor 输出 warning / critical
Intervention Tracker 输出 non_responsive
Intervention Tracker 输出 deteriorating_despite_intervention
Lab 出现关键异常
Patient Memory 更新 unresolved issue
```

## 9.2 定时触发

```text
每 15–30 分钟检查当前高风险患者
每 1 小时检查所有患者
查房前统一生成风险画像
```

---

# 10. 数据库设计

## 10.1 risk_assessments 表

```sql
CREATE TABLE risk_assessments (
    risk_assessment_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    bed_id TEXT NOT NULL,
    assessed_at TIMESTAMP NOT NULL,

    overall_risk_level TEXT NOT NULL,
    active_risks JSONB,
    new_or_worsening_flags JSONB,

    evidence JSONB,
    recommended_next_attention JSONB,
    notify_agents JSONB,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 10.2 risk_events 表

```sql
CREATE TABLE risk_events (
    risk_event_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    bed_id TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL,

    risk_type TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    confidence TEXT,
    trajectory TEXT,
    escalation_level TEXT,

    evidence JSONB,
    source_event_ids JSONB,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

# 11. 与其他 agent 的交互

## 11.1 输入边

```text
Bedside Monitor → Risk Sentinel
Intervention Tracker → Risk Sentinel
Patient Memory → Risk Sentinel
Labs / Notes → Risk Sentinel
```

## 11.2 输出边

```text
Risk Sentinel → Patient Memory
Risk Sentinel → Clinical Summary
Risk Sentinel → Ward Coordinator
```

具体含义：

```text
给 Patient Memory：
记录新的风险变化和风险升级原因。

给 Clinical Summary：
提供当前 active risks 和 evidence，用于生成查房摘要。

给 Ward Coordinator：
提供单患者优先级，用于全 ICU 排序。
```

---

# 12. 和其他 agent 的边界

| Agent                | 回答的问题             |
| -------------------- | ----------------- |
| Bedside Monitor      | 当前生命体征是否异常？       |
| Intervention Tracker | 治疗后有没有改善？         |
| Patient Memory       | 病程主线是什么？          |
| Risk Sentinel        | 当前风险是什么，是否需要升级关注？ |
| Ward Coordinator     | 哪些床位最需要优先处理？      |
| Clinical Summary     | 如何把信息整理成医生可读摘要？   |

---

# 13. 推荐 Agent Prompt

```text
You are the Risk Sentinel Agent for a single ICU patient.

Your task is to synthesize bedside monitoring summaries, intervention response assessments, patient memory, and relevant labs into a structured risk profile.

You do not make final diagnoses, prescribe treatments, or issue medical orders. You identify active clinical risks, explain the evidence, determine risk level, and decide whether the patient should be escalated for human review.

Inputs:
1. Bedside Monitor output.
2. Intervention Tracker output.
3. Patient Memory context.
4. Lab updates and clinical notes when available.

Process:
1. Identify active risk types.
2. Gather evidence from all available inputs.
3. Determine trajectory: improving, stable, worsening, or unclear.
4. Assign risk_level: low, moderate, high, or critical.
5. Assign confidence based on evidence completeness.
6. Generate recommended_next_attention as attention targets, not treatment orders.
7. Return structured JSON only.

Rules:
- Do not provide treatment decisions.
- Do not claim diagnosis certainty.
- Do not ignore intervention response history.
- Escalate risk when deterioration continues after intervention.
- Always include evidence, time window, source agents, and uncertainty.
```

---

# 14. 最小可实现版本

第一版 Risk Sentinel 只需要支持 3 类风险：

```text
1. persistent_shock_risk
2. respiratory_failure_risk
3. aki_risk
```

最小输出：

```json
{
  "patient_id": "P001",
  "bed_id": "B07",
  "overall_risk_level": "high",
  "active_risks": [
    {
      "risk_type": "persistent_shock_risk",
      "risk_level": "high",
      "evidence": [
        "persistent hypotension",
        "limited response to fluid bolus"
      ],
      "trajectory": "worsening"
    }
  ],
  "notify_agents": [
    "ward_coordinator",
    "clinical_summary",
    "patient_memory"
  ]
}
```

