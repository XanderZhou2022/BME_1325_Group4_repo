# Intervention Tracker Agent：单患者设计

## 1. Agent 定位

**Intervention Tracker Agent** 是每个患者独立拥有的床位级治疗追踪 agent。

它不负责判断“医生应该做什么治疗”，也不直接给医嘱。它只回答一个问题：

> 某个治疗干预发生后，患者状态是否出现了符合预期的变化？

也就是说，它是一个 **treatment-response evaluator**。

它关注的是：

* 患者接受了什么治疗
* 治疗发生在什么时候
* 治疗前患者状态如何
* 治疗后患者状态如何
* 变化是否符合预期
* 是否存在“治疗后仍恶化”
* 是否需要提醒 Risk Sentinel 或 Patient Memory 更新

这符合 ICU 系统事件驱动、时间窗口分析和 human-in-the-loop 的设计原则：agent 辅助识别风险和整理证据，但不直接执行医疗决策。

---

# 2. 输入来源

Intervention Tracker 主要接收两类输入。

## 2.1 前端 / 数据发送端传入的治疗事件

由客户端或模拟器向后端发送：

```json
{
  "patient_id": "P001",
  "bed_id": "B07",
  "timestamp": "2026-04-24T13:30:00",
  "intervention_type": "fluid_bolus",
  "intervention_name": "Normal Saline",
  "dose_or_setting": "500ml",
  "route": "IV",
  "reason": "MAP below target",
  "operator": "nurse_or_doctor"
}
```

典型干预类型包括：

```text
fluid_bolus
vasopressor_start
vasopressor_adjustment
sedation_adjustment
ventilator_adjustment
antibiotic_start
antipyretic_given
diuretic_given
blood_transfusion
oxygen_support_change
```

## 2.2 从数据库读取的患者状态数据

它需要读取干预前后窗口的：

```text
vitals:
- HR
- SBP / DBP / MAP
- RR
- SpO2
- Temp

urine_output:
- hourly urine output
- 4h urine output
- ml/kg/h if weight exists

ventilator:
- FiO2
- PEEP
- tidal volume
- peak pressure
- plateau pressure if available

labs:
- lactate
- WBC
- creatinine
- ABG / PaO2 / PaCO2 / pH
```

---

# 3. 输出目标

Intervention Tracker 的输出不是普通文本，而是结构化 JSON。

核心输出包括：

```json
{
  "patient_id": "P001",
  "bed_id": "B07",
  "agent": "intervention_tracker",
  "timestamp": "2026-04-24T14:00:00",
  "intervention_id": "INTV_000123",
  "intervention_type": "fluid_bolus",
  "assessment_window": {
    "pre_window": "30min before intervention",
    "post_window": "30min after intervention"
  },
  "response_label": "partially_responsive",
  "response_summary": "MAP increased after fluid bolus but remained below target.",
  "key_changes": [
    {
      "metric": "MAP",
      "before": "60 mmHg average",
      "after": "64 mmHg average",
      "interpretation": "mild improvement but still below target"
    },
    {
      "metric": "HR",
      "before": "122 bpm average",
      "after": "118 bpm average",
      "interpretation": "slight decrease"
    }
  ],
  "concern_flags": [
    "persistent_hypotension_after_fluid"
  ],
  "urgency_level": "warning",
  "notify_agents": [
    "patient_memory",
    "risk_sentinel"
  ]
}
```

---

# 4. 核心工作逻辑

Intervention Tracker 的一次运行可以分成 6 步。

## Step 1：接收干预事件

当前端发送 intervention event 后，后端先写入 `interventions` 表。

然后 Orchestrator 唤醒该患者对应的 Intervention Tracker。

```text
Frontend / Simulator
        ↓
Backend API
        ↓
interventions table
        ↓
ICU Orchestrator
        ↓
Intervention Tracker Agent
```

---

## Step 2：识别干预类型

不同干预需要观察不同指标。

例如：

| 干预类型                   | 主要观察指标                                 | 典型观察窗口     |
| ---------------------- | -------------------------------------- | ---------- |
| fluid_bolus            | MAP, HR, urine output, lactate         | 15–60 min  |
| vasopressor_adjustment | MAP, HR, lactate                       | 10–60 min  |
| ventilator_adjustment  | SpO₂, PaO₂, FiO₂, RR, peak pressure    | 15–120 min |
| sedation_adjustment    | RASS, HR, BP, RR, ventilator synchrony | 30–120 min |
| antibiotic_start       | Temp, WBC, lactate, vasopressor need   | 6–24 h     |
| antipyretic_given      | Temp, HR                               | 1–4 h      |
| diuretic_given         | urine output, BP, creatinine           | 2–6 h      |
| transfusion            | Hb, HR, BP, SpO₂                       | 1–6 h      |

---

## Step 3：确定前后时间窗口

每个干预都要定义：

```text
pre_window：干预前状态
post_window：干预后状态
expected_response_window：预期起效窗口
```

例如 fluid bolus：

```text
pre_window = intervention_time - 30min 到 intervention_time
post_window = intervention_time 到 intervention_time + 30min
delayed_window = intervention_time + 30min 到 +60min
```

antibiotic 则不能看 30 分钟，需要看 6–24 小时。

---

## Step 4：计算治疗前后变化

Agent 不直接看单点，而是看窗口统计：

```text
before_mean
after_mean
latest_value
delta
delta_percent
trend_direction
target_reached
```

例如：

```json
{
  "metric": "MAP",
  "before_mean": 59.8,
  "after_mean": 64.2,
  "delta": 4.4,
  "target": ">=65",
  "target_reached": false,
  "trend_direction": "improving_but_below_target"
}
```

---

## Step 5：给出 response_label

建议统一使用 5 类标签：

```text
responsive
partially_responsive
non_responsive
deteriorating_despite_intervention
not_enough_data
```

含义如下：

| 标签                                 | 含义                   |
| ---------------------------------- | -------------------- |
| responsive                         | 干预后主要指标明显改善，并达到或接近目标 |
| partially_responsive               | 有改善，但幅度有限或仍未达到目标     |
| non_responsive                     | 干预后无明显改善             |
| deteriorating_despite_intervention | 干预后反而继续恶化            |
| not_enough_data                    | 干预后数据不足，暂不能判断        |

---

## Step 6：通知其他 agent

Intervention Tracker 完成分析后，至少通知两个 agent：

```text
Intervention Tracker → Patient Memory
Intervention Tracker → Risk Sentinel
```

如果 urgency 达到 warning 或 critical，则同时进入 Ward Coordinator 的优先级队列。

```text
Intervention Tracker
        ↓
Patient Memory：记录治疗和反应
        ↓
Risk Sentinel：结合“治疗后仍恶化”重新评估风险
        ↓
Ward Coordinator：如果严重，提升该床位优先级
```

---

# 5. 单患者内部状态设计

Intervention Tracker 应该维护一个患者级 intervention timeline。

```json
{
  "patient_id": "P001",
  "active_interventions": [
    {
      "intervention_id": "INTV_001",
      "type": "fluid_bolus",
      "time": "2026-04-24T13:30:00",
      "status": "under_observation",
      "expected_checkpoints": [
        "2026-04-24T13:45:00",
        "2026-04-24T14:00:00",
        "2026-04-24T14:30:00"
      ]
    }
  ],
  "completed_interventions": [
    {
      "intervention_id": "INTV_000",
      "type": "vasopressor_adjustment",
      "response_label": "responsive",
      "summary": "MAP reached target after norepinephrine increase."
    }
  ]
}
```

---

# 6. 推荐数据库表

## 6.1 interventions 表

记录原始治疗事件。

```sql
CREATE TABLE interventions (
    intervention_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    bed_id TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    intervention_type TEXT NOT NULL,
    intervention_name TEXT,
    dose_or_setting TEXT,
    route TEXT,
    reason TEXT,
    operator TEXT,
    raw_payload JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 6.2 intervention_assessments 表

记录 agent 对干预效果的判断。

```sql
CREATE TABLE intervention_assessments (
    assessment_id TEXT PRIMARY KEY,
    intervention_id TEXT NOT NULL,
    patient_id TEXT NOT NULL,
    bed_id TEXT NOT NULL,
    assessed_at TIMESTAMP NOT NULL,
    pre_window_start TIMESTAMP,
    pre_window_end TIMESTAMP,
    post_window_start TIMESTAMP,
    post_window_end TIMESTAMP,
    response_label TEXT NOT NULL,
    urgency_level TEXT NOT NULL,
    response_summary TEXT,
    key_changes JSONB,
    concern_flags JSONB,
    evidence JSONB,
    notify_agents JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

# 7. 规则逻辑设计

下面是第一版 rule-based 逻辑，适合课程项目落地。

## 7.1 Fluid Bolus 规则

观察指标：

```text
MAP
HR
urine output
lactate if available
```

判定逻辑：

```text
如果 MAP 上升 >= 5 mmHg 且 MAP >= 65：
    responsive

如果 MAP 上升 >= 3 mmHg 但仍 < 65：
    partially_responsive

如果 MAP 变化 < 3 mmHg：
    non_responsive

如果 MAP 下降，或 HR 上升，或 lactate 上升：
    deteriorating_despite_intervention
```

输出例子：

```json
{
  "response_label": "partially_responsive",
  "response_summary": "Fluid bolus was followed by mild MAP improvement, but MAP remained below target.",
  "concern_flags": [
    "persistent_hypotension_after_fluid"
  ],
  "urgency_level": "warning"
}
```

---

## 7.2 Vasopressor Adjustment 规则

观察指标：

```text
MAP
HR
lactate
vasopressor dose
```

判定逻辑：

```text
如果升压药增加后 MAP >= 65：
    responsive

如果 MAP 上升但仍 < 65：
    partially_responsive

如果 MAP 未改善：
    non_responsive

如果升压药增加后 MAP 仍下降：
    deteriorating_despite_intervention
```

额外重要 flag：

```text
increasing_vasopressor_requirement
persistent_shock_signal
```

---

## 7.3 Ventilator Adjustment 规则

观察指标：

```text
SpO2
FiO2
PEEP
RR
peak pressure
ABG if available
```

判定逻辑：

```text
如果 SpO2 改善，且 FiO2 没有继续升高：
    responsive

如果 SpO2 改善但需要更高 FiO2 / PEEP：
    partially_responsive

如果 SpO2 无改善：
    non_responsive

如果 SpO2 下降，RR 上升，或 peak pressure 明显升高：
    deteriorating_despite_intervention
```

concern flags：

```text
persistent_hypoxemia_after_ventilator_change
possible_worsening_respiratory_failure
high_airway_pressure_after_adjustment
```

---

## 7.4 Antibiotic Start 规则

抗生素不能短窗口判断，建议分成 delayed assessment。

观察窗口：

```text
6h
12h
24h
```

观察指标：

```text
Temp
WBC
lactate
MAP
vasopressor requirement
```

判定逻辑：

```text
如果 24h 内体温下降、lactate 下降、升压药需求下降：
    responsive

如果部分指标改善：
    partially_responsive

如果无改善：
    non_responsive

如果发热持续、lactate 上升、升压药需求增加：
    deteriorating_despite_intervention
```

---

# 8. Agent 的运行时机

Intervention Tracker 不是只运行一次，而是分阶段运行。

## 8.1 干预刚发生时

立即记录：

```text
status = pending_assessment
```

并生成观察计划：

```text
fluid_bolus: 15min / 30min / 60min
vasopressor: 10min / 30min / 60min
ventilator: 15min / 60min / 120min
antibiotic: 6h / 12h / 24h
```

## 8.2 到达观察检查点时

系统自动重新唤醒 Intervention Tracker：

```text
check_intervention_response
```

## 8.3 新 vitals 到达时

如果某个患者存在 active intervention，则 Intervention Tracker 可以被动更新观察状态。

---

# 9. 和 Bedside Monitor 的区别

这两个 agent 很容易混淆，边界要清楚。

| Agent                | 关注点        | 问的问题         |
| -------------------- | ---------- | ------------ |
| Bedside Monitor      | 当前生命体征是否异常 | 现在患者状态如何？    |
| Intervention Tracker | 治疗前后是否变化   | 做了治疗以后有没有效果？ |

例子：

```text
Bedside Monitor:
过去 30 分钟 MAP 持续低于 65，存在低血压。

Intervention Tracker:
13:30 补液 500ml 后，MAP 从 60 上升到 64，但仍未达到目标，属于部分反应。
```

---

# 10. 最终推荐的 Agent prompt

可以给代码助手或 LLM agent 使用：

```text
You are the Intervention Tracker Agent for a single ICU patient.

Your task is to evaluate the relationship between treatment interventions and subsequent patient state changes. You do not make treatment decisions or issue medical orders. You only assess whether a recorded intervention was followed by improvement, no response, partial response, or deterioration.

Inputs:
1. A single intervention event, including patient_id, bed_id, timestamp, intervention_type, intervention_name, dose_or_setting, and reason.
2. Time-windowed patient data before and after the intervention, including vitals, urine output, ventilator parameters, and labs when available.
3. Optional previous intervention history for the same patient.

Process:
1. Identify the intervention type.
2. Select the appropriate pre- and post-intervention observation windows.
3. Compare clinically relevant metrics before and after the intervention.
4. Determine one response_label from:
   - responsive
   - partially_responsive
   - non_responsive
   - deteriorating_despite_intervention
   - not_enough_data
5. Generate concise evidence explaining the label.
6. Assign urgency_level:
   - info
   - warning
   - critical
7. Return structured JSON only.

Rules:
- Do not recommend new treatments.
- Do not produce a final diagnosis.
- Do not claim causality with certainty; use wording such as “was followed by” or “suggests limited response”.
- Always include evidence, time_window, and key metric changes.
- If post-intervention data are insufficient, return not_enough_data.
```

---

# 11. 最小可实现版本

如果现在马上落地，我建议第一版只支持 4 类 intervention：

```text
1. fluid_bolus
2. vasopressor_adjustment
3. ventilator_adjustment
4. antibiotic_start
```

第一版只需要输出：

```json
{
  "intervention_id": "...",
  "patient_id": "...",
  "intervention_type": "...",
  "response_label": "...",
  "response_summary": "...",
  "key_changes": [],
  "concern_flags": [],
  "urgency_level": "...",
  "notify_agents": []
}
```

这样就已经可以和后面的 **Patient Memory**、**Risk Sentinel** 串起来了。
