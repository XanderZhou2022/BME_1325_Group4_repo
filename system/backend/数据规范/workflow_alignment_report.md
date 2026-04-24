# ICU Workflow 对照报告（实现版）

## 已对齐

- Agent 链路与角色分层已落地：`bedside_monitor -> intervention_tracker -> patient_memory -> risk_sentinel -> clinical_summary -> ward_coordinator`。
- 核心事件与状态表齐全：`events`、`vital_sign_events`、`lab_events`、`intervention_events`、`agent_outputs`、`agent_events`、`patient_state_current`。
- orchestrator 可记录运行回放：`orchestrator_runs.step_results`。

## 本次补齐

- 事件驱动分发：`event_pipeline` 写入事件后，路由层触发 `event_dispatcher`，按 `vital/intervention/lab` 执行最小链路。
- intervention pending 生命周期：新增 `intervention_pending`，支持 `pending -> insufficient_data/completed` 并提供到窗评估入口。
- 周期调度：新增 `scheduler_loop` 与手动 `POST /api/v1/orchestrator/scheduler/tick`。
- 可观测增强：
  - 增加 lifecycle 事件 `agent_name.started/completed/failed`；
  - 扩展 `StepResult`：`input_sources/input_window/output_id/error_class/retry_count`；
  - dispatcher/orchestrator 写入更完整 `audit_logs`。
- ward 持久化：`ward_coordinator` 补齐 `agent_outputs` 与 `agent_events` 写库。

## 仍建议后续优化

- pending 状态可进一步细分 `ready_for_evaluation/expired` 的定时状态迁移。
- `output_id` 目前在 orchestrator step 中仍未反向关联，可在 agent service 返回输出主键后完全补齐。
- `clinical_summary` 与 `ward_coordinator` 可增加“仅风险变化时触发”的去抖策略，减少高频重算。
