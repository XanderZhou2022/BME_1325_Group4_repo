bedside_monitor 落实顺序
1. 固定运行入口

只处理单患者：

run_bedside_monitor(admission_id)

输入参数最少只需要：

admission_id
window_minutes = 90
trend_hours = 6
2. 固定读取数据

从数据库读取：

admissions
patients
beds
vital_sign_events
patient_state_current
recent lab_events 可选
recent intervention_events 可选

核心是：

最近 90 分钟 vitals：判断当前异常
最近 6 小时 vitals：判断趋势
3. 固定输出 schema

bedside_monitor 输出建议固定为：

{
  "schema_version": "bedside_monitor.v1",
  "agent_name": "bedside_monitor",
  "admission_id": "adm1",
  "patient_id": "p1",
  "bed_id": "b1",
  "time_window": {
    "start": "timestamp",
    "end": "timestamp",
    "window_minutes": 90
  },
  "current_status_summary": "MAP remains below target with persistent tachycardia.",
  "abnormal_flags": [
    {
      "type": "low_map",
      "severity": "warning",
      "metric": "mean_arterial_pressure",
      "value": 60,
      "threshold": "<65",
      "duration_minutes": 30
    }
  ],
  "trend_labels": [
    {
      "metric": "mean_arterial_pressure",
      "trend": "decreasing",
      "evidence": "MAP decreased from 72 to 60 over the last 6 hours."
    }
  ],
  "evidence": {
    "latest_vitals": {},
    "summary_stats": {},
    "data_points_count": 12
  },
  "urgency_level": "warning",
  "next_action_hint": "Recommend risk_sentinel review if hypotension persists."
}
4. 固定规则逻辑

第一版不要复杂，先做规则稳定。

MAP
MAP < 65 → warning
MAP < 60 持续 ≥ 15 min → critical
SpO2
SpO2 < 92 → warning
SpO2 < 88 → critical
HR
HR > 120 → warning
HR > 140 → critical
HR < 50 → warning
HR < 40 → critical
RR
RR > 24 → warning
RR > 30 → critical
RR < 8 → critical
Temp
Temp >= 38.5 → warning
Temp >= 39.5 → critical
Temp < 35 → warning/critical
GCS
GCS < 13 → warning
GCS <= 8 → critical
5. 固定趋势判断

趋势先简单做：

最近 6 小时第一个值 vs 最新值

例如：

MAP 下降 ≥ 10 mmHg → decreasing
HR 上升 ≥ 20 bpm → increasing
SpO2 下降 ≥ 4% → decreasing
Temp 上升 ≥ 1°C → increasing
6. 固定写库位置

bedside_monitor 完成后写：

agent_outputs
agent_events
audit_logs
patient_state_current.current_vitals
patient_state_current.care_phase 可选

如果：

urgency_level = warning / critical

则写入 agent_events：

bedside_monitor.warning_detected
bedside_monitor.critical_detected

给 orchestrator 后续触发 patient_memory / risk_sentinel。

可以直接给代码助手的任务
请先落实 bedside_monitor agent，不要修改其他 agent 逻辑。

目标：
实现单患者 bedside_monitor 的稳定规则版闭环。

范围：
`system/backend/app/agents/bedside_monitor/`

要求：

1. 暴露统一运行函数：
   `run_bedside_monitor(admission_id: str, window_minutes: int = 90, trend_hours: int = 6)`

2. 从数据库读取：
   - admissions
   - patients
   - beds
   - vital_sign_events
   - patient_state_current
   - 可选读取 recent lab_events / intervention_events

3. 使用最近 90 分钟 vitals 判断当前异常；
   使用最近 6 小时 vitals 判断趋势。

4. 输出必须符合 bedside_monitor.v1 schema，至少包含：
   - schema_version
   - agent_name
   - admission_id
   - patient_id
   - bed_id
   - time_window
   - current_status_summary
   - abnormal_flags
   - trend_labels
   - evidence
   - urgency_level
   - next_action_hint

5. 规则阈值：
   - MAP < 65 warning；MAP < 60 且持续 >=15min critical
   - SpO2 < 92 warning；SpO2 < 88 critical
   - HR > 120 warning；HR > 140 critical；HR < 50 warning；HR < 40 critical
   - RR > 24 warning；RR > 30 critical；RR < 8 critical
   - Temp >= 38.5 warning；Temp >= 39.5 critical；Temp < 35 warning/critical
   - GCS < 13 warning；GCS <= 8 critical

6. 写库：
   - 完整输出写入 agent_outputs
   - started/completed 事件写入 agent_events
   - 输入窗口、输出、异常和错误写入 audit_logs
   - 最新生命体征摘要写入 patient_state_current.current_vitals
   - 如 urgency_level 为 warning/critical，写对应 agent_event 供 orchestrator 后续触发

7. 错误处理：
   - 没有 vitals 时返回 degraded，不要让 orchestrator 崩溃
   - 数据字段缺失时跳过对应指标，但在 evidence.data_quality 中记录 missing fields
   - 所有 Decimal / datetime 必须 JSON serializable

8. 不接 LLM。
   bedside_monitor 第一版只做规则逻辑，作为后续 LLM 的 fallback。

这一版做完以后，我们再检查 bedside_monitor 的真实输出，再决定是否接入 LLM。