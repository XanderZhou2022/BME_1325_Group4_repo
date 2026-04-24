Clinical Summary Agent 设计
1. Agent 定位

Clinical Summary Agent 是 ICU 系统里的临床摘要生成 agent。

它不直接读取所有原始生命体征，也不做风险判断，而是整合前面 agent 已经处理好的结构化结果，生成医生、护士查房时可以快速阅读的摘要。

它回答的问题是：

这个患者现在是什么状态？过去一段时间发生了什么？当前最需要关注的临床问题是什么？

2. 输入来源

Clinical Summary 主要读取：

Patient Memory Agent
Risk Sentinel Agent
Intervention Tracker Agent
Bedside Monitor Agent
Labs / Notes

其中优先级如下：

1. Risk Sentinel：当前活跃风险
2. Patient Memory：病程主线和未解决问题
3. Intervention Tracker：关键干预及反应
4. Bedside Monitor：最新状态摘要
5. Labs / Notes：补充事实
3. 输出类型

Clinical Summary 建议生成 3 种摘要。

3.1 单患者当前摘要

用于单床详情页。

Bed 07 当前主要问题是循环不稳定。过去6小时 MAP 多次低于目标，补液后仅部分改善，Risk Sentinel 标记为 persistent_shock_risk high。当前仍需重点关注低血压持续和乳酸趋势。
3.2 单患者 24h 查房摘要

用于医生查房。

患者因感染性休克收入 ICU。过去24小时循环支持需求增加，MAP 多次低于目标，补液反应有限，乳酸呈上升趋势。当前主要问题包括持续性休克风险、低尿量和感染控制情况待观察。建议查房时优先复核血流动力学状态、乳酸趋势和近期干预反应。
3.3 ICU 全病房摘要输入

给 Ward Coordinator 使用：

{
  "patient_id": "P001",
  "bed_id": "B07",
  "summary_for_ward": "Bed 07: high shock risk, worsening trajectory, limited response to fluid bolus.",
  "priority_reasons": [
    "high persistent_shock_risk",
    "worsening trajectory",
    "limited intervention response"
  ]
}
4. 标准输出 JSON
{
  "patient_id": "P001",
  "bed_id": "B07",
  "agent": "clinical_summary",
  "timestamp": "2026-04-24T15:00:00",
  "summary_type": "24h_round_summary",
  "clinical_summary": {
    "one_line_status": "Bed 07 remains hemodynamically unstable with high persistent shock risk.",
    "icu_course_context": "Patient was admitted for septic shock and remains on circulatory support.",
    "last_24h_key_events": [
      "MAP repeatedly below target",
      "Fluid bolus produced only partial response",
      "Lactate trend increased",
      "Risk Sentinel marked persistent_shock_risk as high"
    ],
    "active_problem_list": [
      {
        "problem": "Persistent shock risk",
        "status": "active",
        "trajectory": "worsening",
        "supporting_evidence": [
          "persistent hypotension",
          "limited fluid response",
          "rising lactate"
        ]
      }
    ],
    "key_interventions_and_responses": [
      {
        "intervention": "Fluid bolus 500ml",
        "response": "partially_responsive",
        "summary": "MAP improved mildly but remained below target."
      }
    ],
    "recommended_attention_targets": [
      "hemodynamic status",
      "lactate trend",
      "response to recent interventions"
    ],
    "uncertainties_or_missing_data": [
      "latest lactate not available after 14:00"
    ]
  },
  "urgency_level": "warning",
  "notify_agents": [
    "ward_coordinator",
    "compassion_agent"
  ]
}
5. 核心工作流程
Step 1：确定摘要类型

Clinical Summary 先判断当前任务：

current_status_summary
24h_round_summary
shift_handoff_summary
ward_level_brief
family_translation_basis

不同任务使用不同长度和重点。

Step 2：读取结构化上下文

读取最近：

Patient Memory 最新版本
Risk Sentinel 最新 active risks
Intervention Tracker 最近 24h 关键干预
Bedside Monitor 最近 1–6h 状态摘要
Labs / Notes 最新关键结果
Step 3：构建问题列表

Clinical Summary 要把零散信息整理成 problem list。

例如：

1. Persistent shock risk
2. Respiratory failure risk
3. AKI risk
4. Infection control pending
5. Sedation / delirium issue

每个 problem 包含：

problem_name
status: active / improving / resolved / unclear
trajectory: improving / stable / worsening / unclear
evidence
last_updated
Step 4：总结时间线

摘要必须体现时间顺序：

入 ICU 原因
过去24小时关键变化
最近6小时变化
当前最需要关注的问题

推荐结构：

背景 → 24h变化 → 当前风险 → 干预反应 → 待关注点
Step 5：生成医护可读摘要

注意：Clinical Summary 的语言应该专业但简洁。

不写长篇推理，不写未经证实的诊断，不写治疗命令。

正确表达：

过去6小时 MAP 持续低于目标，补液后改善有限，提示循环状态仍需重点复核。

避免表达：

应该立即加大升压药剂量。
6. 摘要模板
6.1 当前状态摘要模板
[Bed ID] 当前主要问题为 [main active problem]。最近 [time window] 内，[key abnormal trend]。近期干预 [intervention] 后反应为 [response_label]。当前风险等级为 [risk_level]，主要依据包括 [evidence list]。
6.2 24h 查房摘要模板
患者因 [admission reason] 收入 ICU。过去24小时主要变化为：[key events]。当前 active problems 包括：[problem list]。近期重要干预包括：[interventions and responses]。目前最需要查房时关注：[attention targets]。缺失或待确认信息：[uncertainties]。
6.3 交班摘要模板
本班期间，患者 [overall trajectory]。主要事件包括：[events during shift]。当前未解决问题包括：[unresolved issues]。需要下一班继续关注：[next shift watch items]。
7. 数据库设计
clinical_summaries 表
CREATE TABLE clinical_summaries (
    summary_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    bed_id TEXT NOT NULL,
    generated_at TIMESTAMP NOT NULL,

    summary_type TEXT NOT NULL,
    one_line_status TEXT,
    clinical_summary TEXT,

    active_problem_list JSONB,
    key_events JSONB,
    key_interventions_and_responses JSONB,
    recommended_attention_targets JSONB,
    uncertainties_or_missing_data JSONB,

    urgency_level TEXT,
    source_event_ids JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
8. 运行时机

Clinical Summary 不是高频 agent，建议低频运行。

8.1 定时运行
每天查房前：生成 24h round summary
每班交班前：生成 shift handoff summary
每 1 小时：更新高风险患者 current status summary
8.2 事件触发
Risk Sentinel 输出 high / critical
Intervention Tracker 输出 deteriorating_despite_intervention
Patient Memory 出现新的重大事件
Ward Coordinator 请求全病房摘要
Compassion Agent 需要家属版摘要基础
9. 和其他 agent 的交互
输入边
Patient Memory → Clinical Summary
Risk Sentinel → Clinical Summary
Intervention Tracker → Clinical Summary
Bedside Monitor → Clinical Summary
Ward Coordinator → Clinical Summary
输出边
Clinical Summary → Ward Coordinator
Clinical Summary → Compassion Agent
Clinical Summary → Frontend Dashboard
Clinical Summary → Audit Log
10. 与其他 agent 的边界
Agent	作用
Patient Memory	维护病程上下文
Risk Sentinel	判断风险等级
Intervention Tracker	判断干预反应
Clinical Summary	把结构化结果写成医护可读摘要
Ward Coordinator	多床位排序
Compassion Agent	转成家属可理解版本

Clinical Summary 不应该新增医学判断，只应该整合已有判断。

11. 推荐 Agent Prompt
You are the Clinical Summary Agent for an ICU multi-agent simulation system.

Your task is to generate concise, clinically readable summaries from structured outputs produced by other agents. You do not make new diagnoses, prescribe treatments, or issue medical orders.

Inputs:
1. Patient Memory summary.
2. Risk Sentinel risk profile.
3. Intervention Tracker intervention-response assessments.
4. Bedside Monitor status summaries.
5. Relevant labs and clinical notes.

Process:
1. Determine the requested summary type.
2. Extract the patient's ICU course context.
3. Identify active problems and unresolved issues.
4. Summarize key changes in the requested time window.
5. Summarize important interventions and responses.
6. Include attention targets and missing data.
7. Return structured JSON only.

Rules:
- Do not invent facts not present in input.
- Do not recommend treatment orders.
- Use professional but concise clinical language.
- Preserve uncertainty when evidence is incomplete.
- Always include source evidence and time windows.
12. 最小可实现版本

第一版只需要支持：

1. current_status_summary
2. 24h_round_summary

最小输出：

{
  "patient_id": "P001",
  "bed_id": "B07",
  "summary_type": "current_status_summary",
  "one_line_status": "Bed 07 has persistent hemodynamic instability with high shock risk.",
  "key_events": [
    "MAP repeatedly below target",
    "Fluid bolus produced partial response"
  ],
  "active_problem_list": [
    "persistent_shock_risk"
  ],
  "recommended_attention_targets": [
    "hemodynamic status",
    "intervention response",
    "lactate trend"
  ],
  "urgency_level": "warning"
}