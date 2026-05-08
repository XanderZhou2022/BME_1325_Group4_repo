# Agent Contract（v1）

本文档用于把 ICU 多智能体系统的 Agent 从“能跑”升级为“契约化可审计”。

目标：

1. 固定每个 agent 的输入来源（Input Sources）
2. 固定每个 agent 的输出结构（Output Schema）
3. 固定写库目标（Write Targets）
4. 固定事件发布类型（Event Type）与 schema 版本
5. 为后续 LLM 接入提供统一边界

---

## 0. 全局约定

### 0.1 统一版本

- `schema_version`: `v1`
- 新增字段时：在不破坏旧字段语义前提下可向后兼容
- 破坏性变更必须升级版本（例如 `v2`）并保留迁移说明

### 0.2 通用主键与上下文字段

所有 agent 输出建议携带以下上下文：

- `admission_id`
- `patient_id`
- `bed_id`
- `generated_at`（ISO8601 UTC）

### 0.3 统一写库路径

- 结构化输出：`agent_outputs`
- 事件通知：`agent_events`
- 消费游标（仅消费者）：`agent_consumption_cursor`
- 运行注册信息：`agent_registry`

### 0.4 命名规范

- `agent_name`: snake_case（如 `risk_sentinel`）
- `output_type` = `event_type`
- `event_type` 统一使用 `*_ready` 后缀

---

## 1. bedside_monitor

### 1.1 Input Sources

- 主输入表：`vital_sign_events`
- 请求参数：`analysis_window`, `analysis_end`, `urine_output_points`

### 1.2 Output Schema (`bedside_analysis_ready`)

```json
{
  "analysis_window": "last_4h",
  "current_status_summary": "...",
  "abnormal_flags": [],
  "trend_labels": [],
  "evidence": [],
  "urgency_level": "info|warning|critical",
  "generated_at": "timestamp"
}
```

### 1.3 Write Targets

- `agent_registry`:
  - `agent_name = bedside_monitor`
  - `input_event_types = ["vital_sign"]`
  - `output_event_type = bedside_analysis_ready`
- `agent_outputs`:
  - `agent_name = bedside_monitor`
  - `output_type = bedside_analysis_ready`
- `agent_events`:
  - `producer_agent = bedside_monitor`
  - `event_type = bedside_analysis_ready`

### 1.4 Contract Notes

- 若窗口内无 vital 数据，返回 404（由上层编排处理）
- 输出必须保持字段稳定，允许 `evidence` 扩展字段

---

## 2. intervention_tracker

### 2.1 Input Sources

- 主输入表：`intervention_events`
- 辅助输入表：`vital_sign_events`（干预前后窗口）
- 请求参数：`intervention_id`, `pre_window_minutes`, `post_window_minutes`

### 2.2 Output Schema (`intervention_evaluation_ready`)

```json
{
  "intervention_type": "fluid|vasopressor|ventilator_change",
  "intervention_time": "timestamp",
  "observation_window": "pre 60m / post 60m",
  "response_assessment": "improving|non_responsive|deteriorating_despite_intervention",
  "target_metrics": {},
  "before_after_comparison": {},
  "evidence": [],
  "escalation_hint": "...",
  "generated_at": "timestamp"
}
```

### 2.3 Write Targets

- `agent_registry`: `intervention_tracker`
- `agent_outputs`: `output_type = intervention_evaluation_ready`
- `agent_events`: `event_type = intervention_evaluation_ready`

---

## 3. patient_memory

### 3.1 Input Sources

- 主输入表：
  - `vital_sign_events`
  - `lab_events`
  - `intervention_events`
- 请求参数：`window_hours`

### 3.2 Output Schema (`patient_memory_ready`)

```json
{
  "window_hours": 24,
  "current_vitals": {},
  "trend_vectors": {},
  "volatility_index": {},
  "latest_interventions": [],
  "data_completeness_ratio": 0.0,
  "snapshot_generated_at": "timestamp"
}
```

### 3.3 Write Targets

- `agent_registry`: `patient_memory`
- `agent_outputs`: `output_type = patient_memory_ready`
- `agent_events`: `event_type = patient_memory_ready`

### 3.4 备注

- 当前实现为“窗口摘要型 memory”；
- 后续 history memory 优化须保证上述输出结构不破坏。

---

## 4. risk_sentinel

### 4.1 Input Sources

- 事件输入（增量）：`agent_events`
  - 生产者：`bedside_monitor`, `intervention_tracker`, `patient_memory`
- 最新快照输入：`agent_outputs`（bedside/intervention）
- 消费游标：`agent_consumption_cursor`

### 4.2 Output Schema (`risk_assessment_ready`)

```json
{
  "risks": [
    {
      "risk_type": "shock|respiratory_failure|persistent_hypoperfusion",
      "severity": "low|warning|critical",
      "confidence": 0.93,
      "evidence": [],
      "time_window": "latest",
      "recommended_action": "..."
    }
  ],
  "consumed_event_ids": []
}
```

### 4.3 Write Targets

- `risk_assessments`（风险明细）
- `alerts`（告警）
- `patient_state_current.active_risks`（风险回写）
- `agent_outputs`: `output_type = risk_assessment_ready`
- `agent_events`: `event_type = risk_assessment_ready`
- `agent_consumption_cursor`（更新游标）

### 4.4 约束

- 写入 `agent_outputs/agent_events` 前需确保 JSON 可序列化（如 Decimal->float）

---

## 5. clinical_summary

### 5.1 Input Sources

- `agent_outputs`（`bedside_monitor`, `intervention_tracker`, `patient_memory`）
- `risk_assessments`
- `admissions`（admission_reason）

### 5.2 Output Schema (`clinical_summary_ready`)

```json
{
  "24h_rounds_summary": "...",
  "problem_list": [],
  "focus_areas_for_today": [],
  "clinical_narrative": "..."
}
```

### 5.3 Write Targets

- `agent_registry`: `clinical_summary`
- `agent_outputs`: `output_type = clinical_summary_ready`
- `agent_events`: `event_type = clinical_summary_ready`

---

## 6. ward_coordinator

### 6.1 Input Sources

- `patient_state_current`（全 active admission）
- 可结合 `alerts` / `risk_assessments`（后续扩展）

### 6.2 Output Schema (`ward_coordinator_ready`, 建议统一)

```json
{
  "generated_at": "timestamp",
  "active_admission_count": 0,
  "priority_queue": [
    {
      "admission_id": "...",
      "patient_id": "...",
      "bed_id": "...",
      "care_phase": "critical|unstable|stable",
      "priority_score": 100,
      "reason": "care_phase=critical, max_risk=critical"
    }
  ],
  "pending_actions": [],
  "ward_load_indicator": "normal|medium|high",
  "alert_storm_summary": {}
}
```

### 6.3 Write Targets

- 当前 service 已返回结构化结果；建议与其它 agent 一致：
  - 写 `agent_outputs`
  - 发 `agent_events`
  - `event_type = ward_coordinator_ready`

> 说明：当前最小实现中 `ward_coordinator` 主要由 orchestrator 调用并返回；建议下一阶段补齐写库与事件发布，完成全链路可回放。

---

## 7. Orchestrator Contract（流程层）

### 7.1 Pipeline 顺序

1. `bedside_monitor`
2. `intervention_tracker`
3. `patient_memory`
4. `risk_sentinel`
5. `clinical_summary`
6. `ward_coordinator`

### 7.2 Run 输出

- 写 `orchestrator_runs`：
  - `run_id`
  - `target_admissions`
  - `step_results`（每 step status/detail）
- 写 `audit_logs`：记录一次 run 行为

### 7.3 StepResult 最小字段

```json
{
  "step_name": "risk_sentinel",
  "admission_id": "ICU-ADM-0001",
  "status": "ok|error|skipped",
  "started_at": "timestamp",
  "finished_at": "timestamp",
  "detail": {}
}
```

---

## 8. LLM 接入规范（下一阶段）

每个 agent 目录建议固定文件结构：

- `rules.py`：规则/特征提取
- `contract.py`：本文件对应的契约常量（可代码化）
- `llm.py`：Prompt + JSON 校验 + 重试策略
- `service.py`：读库/写库 + 调用 llm/rules
- `router.py`：API 入口

建议 `contract.py` 至少包含：

- `AGENT_NAME`
- `INPUT_SOURCES`
- `OUTPUT_EVENT_TYPE`
- `OUTPUT_SCHEMA_VERSION`
- `WRITE_TARGETS`
- `LLM_PROMPT_VERSION`

---

## 9. 变更治理

1. 任一 agent 输出结构变更，先更新 contract，再改 service
2. 变更必须同步更新：
   - `agent_registry` schema_version
   - OpenAPI schema（如有）
   - 前端展示字段映射
3. 生产前必须通过：
   - schema 合法性检查
   - orchestrator 全流程回归
   - 可视化页面字段兼容检查
