给代码助手的任务说明

我们现在在第一层（Bedside Monitor Agent 与 Intervention Tracker Agent）的基础上，实现 ICU 系统的第二层核心模块：Patient Memory Agent 与 Risk Sentinel Agent。
这一阶段的目标是补齐“时序状态管理”与“量化风险评估”能力，为后续的全局告警编排与多智能体协同提供标准化数据底座。

一、实现原则

这两个 agent 延续第一层的开发约束，并严格对齐项目现有数据规范：
- 以 `admission_id` 为时序分析主锚点（参考《数据库使用规范.md》第8.3节），不依赖全局 orchestrator，不调用 LLM。
- 技术栈：Python + FastAPI + Pydantic + 规则/算法驱动。
- 输入输出字段命名、枚举值、JSONB 结构必须与《数据类型.md》及 `risk_assessments` / `alerts` / `patient_state_current` 表定义完全一致。
- 输出结果需支持直接写入对应业务表或通过 `/api/v1/` 路由入库。

Patient Memory Agent 负责“时间窗口的数据聚合与状态快照管理”。
Risk Sentinel Agent 负责“动态临床风险量化”，核心采用 APACHE II 评分逻辑，并显式融合 Intervention Tracker Agent 的干预反应评估结果。

二、Patient Memory Agent 要做什么

Patient Memory Agent 的职责是：
维护 `vital_sign_events`、`lab_events` 与 `intervention_events` 的时序窗口，提供平滑后的结构化状态视图，输出符合 `patient_state_current` 与 `patient_state_snapshots` 规范的数据结构。

输入

- `admission_id` (str): 住院唯一标识（主查询键）
- `window_hours` (int): 时间窗口（6 / 24 / 72，默认 6）
- `vital_sign_events` (List[Dict]): 严格对齐《数据类型.md》字段：
  `heart_rate`, `mean_arterial_pressure`, `systolic_bp`, `diastolic_bp`, `respiratory_rate`, `temperature`, `spo2`, `fio2`, `pao2`, `aado2`, `ph`, `gcs`, `timestamp`
- `lab_events` (List[Dict]): 字段：`lab_type`, `value`, `unit`, `abnormal_flag`, `timestamp`
- `intervention_events` (List[Dict]): 字段：`intervention_type`, `description`, `dosage`, `unit`, `timestamp`

输出

统一输出 `TemporalStateSummary`（结构对齐 `patient_state_current` 规范）：
{
  "admission_id": "adm1",
  "window_hours": 6,
  "current_vitals": { "heart_rate": 92, "mean_arterial_pressure": 74, "spo2": 96, "temperature": 37.8, ... },
  "trend_vectors": { "mean_arterial_pressure": "stable", "spo2": "improving", "temperature": "worsening" },
  "volatility_index": { "heart_rate": 0.15, "mean_arterial_pressure": 0.08 },
  "latest_interventions": [ { "intervention_type": "fluid", "timestamp": "...", "response_hint": "partially_responsive" } ],
  "data_completeness_ratio": 0.94,
  "snapshot_generated_at": "TIMESTAMPTZ"
}

其中：
- `current_vitals`：窗口内按临床惯例取“最差值(worst)”或“滑动平均”。APACHE II 要求取最差值，此处需保留原始统计以供上层调用。
- `trend_vectors`：基于窗口前后半段差值或线性回归斜率，输出 `stable` / `improving` / `worsening` / `fluctuating`。
- `latest_interventions`：与 Intervention Tracker 输出对齐，按时间倒序取最近 3 次。
- 缺失值处理：线性插值或前向填充，同时记录 `data_completeness_ratio`，低于阈值（如 <0.7）时触发质量标记。

第一阶段分析逻辑

- 窗口切片：按 `timestamp` 排序，支持重叠窗口查询。
- 多源合并：`vital_sign_events` 与 `lab_events` 按时间对齐，统一纳入时序矩阵。
- 事件堆叠：将干预事件与时间窗对齐，计算干预前后指标偏移量，生成 `response_hint` 预评估。
- 不做临床解释，只做数据对齐、窗口切片、统计聚合与趋势标签生成。

三、Risk Sentinel Agent 要做什么

Risk Sentinel Agent 的职责是：
基于 APACHE II 评分系统进行动态风险量化，并结合 Intervention Tracker 的干预反应评估，输出结构化风险分层与趋势提示。输出需严格匹配 `risk_assessments` 表结构与 `alerts` 表枚举规范。

输入

- `admission_id` (str)
- `temporal_state` (Dict): 来自 Patient Memory Agent 的聚合结果
- `age` (int), `chronic_health_status` (str), `is_elective_surgery` (bool): 来自 `patients` / `admissions` 上下文
- `window_hours` (int): 默认 24h（模拟入院/评估周期）

输出

统一输出 `RiskAssessment`（可直接写入 `risk_assessments` 表）：
{
  "admission_id": "adm1",
  "timestamp": "TIMESTAMPTZ",
  "risk_type": "apache_ii_comprehensive",
  "confidence": 0.85,
  "severity": "warning",
  "evidence": [
    {"param": "mean_arterial_pressure", "worst_value": 58, "score": 2, "reason": "持续低于65"},
    {"param": "temperature", "worst_value": 39.2, "score": 3, "reason": "高热"}
  ],
  "time_window": "last_24h",
  "recommended_action": "review fluid response & vasopressor titration",
  "apache_ii_breakdown": { "physiology": 14, "age": 2, "chronic_health": 2, "total": 18 },
  "intervention_context_impact": "deteriorating_despite_intervention",
  "urgency_adjusted": true,
  "trend_direction": "worsening"
}

其中：
- `severity` 枚举严格对齐数据库：`low` / `warning` / `critical`。
- `risk_type`：如 `apache_ii_comprehensive`, `hemodynamic_instability`, `respiratory_failure`。
- `evidence`：JSONB 数组结构，每项建议含 `param`, `value` (或 `worst_value`), `score`, `reason`，方便前端渲染与审计。
- 干预融合：若 `intervention_context_impact` 为 `non_responsive` 或 `deteriorating_despite_intervention`，则 `urgency_adjusted = true`，并在 `severity` 映射时上调一级（受限于枚举上限 `critical`）。

第一阶段分析逻辑

1. APACHE II 规则计算（严格对照《APACHE II 评分系统.md》）：
   - 对 12 项生理参数按窗口内“最差值”查表映射得分。GCS 得分 = `15 - 实际GCS`。
   - 年龄分段查表累加。慢性健康状态按择期/急诊或未手术区分 +2 / +5。
   - 缺省指标（如无 `pao2`/`aado2`）默认 0 分，`confidence` 相应下调。
2. 干预反应融合：
   - 读取 `temporal_state.latest_interventions` 中的 `response_hint`。
   - 若为 `responsive` / `partially_responsive`：标记风险趋势 `stabilizing`。
   - 若为 `non_responsive` / `deteriorating_despite_intervention`：触发 `urgency_adjusted`，`trend_direction` 标记 `worsening`，并在 `recommended_action` 追加“需人工复核干预策略”。
3. 风险分级与输出：
   - 计算总分 → 映射临床风险带（<10 低危, 10-14 中低, 15-25 中高危, >25 高危）。
   - 生成 `risk_assessments` 兼容结构。若 `severity` 为 `warning` 或 `critical`，同步生成 `alerts` 表兼容结构（`alert_type`, `severity: info/warning/critical`, `status: open`, `source_agent: risk_sentinel`）。

四、这两个 agent 先不要做什么

- 不做跨床位负载评估或 Ward Coordinator 调度
- 不自动生成临床诊疗建议或处方（仅输出 `recommended_action` 提示词）
- 不接入 LLM 进行自由文本推理
- 不实现完整的告警风暴抑制算法（仅输出单床位风险等级与干预上下文标记）
- 不修改原始监测数据（Memory Agent 只做聚合，不改写底层 `vital_sign_events`）

第二层的核心是“把第一层的原始/干预数据转化为可计算的风险状态”，为第三层的人类在环决策与全局编排提供标准化输入。

五、建议的目录结构

backend/
  agents/
    patient_memory/
      schemas.py          # Pydantic 模型（严格对齐 DB JSONB 结构）
      memory_manager.py   # 窗口管理、插值、趋势计算
      service.py          # 主逻辑封装
      router.py           # FastAPI 路由
      examples.py         # 测试样例数据（使用真实字段名）
    risk_sentinel/
      schemas.py
      apache_ii_rules.py  # APACHE II 评分查表与逻辑映射
      service.py          # 评分计算 + 干预上下文融合
      router.py
      examples.py
  api/
  数据规范/
  测试数据库/

六、接口建议

1. Patient Memory Agent
POST /api/v1/agents/patient-memory/state
输入：`admission_id`, `vital_sign_events`, `lab_events`, `intervention_events`, `window_hours`
输出：`TemporalStateSummary`（兼容 `patient_state_current` 写入格式）

2. Risk Sentinel Agent
POST /api/v1/agents/risk-sentinel/evaluate
输入：`admission_id`, `temporal_state`, `age`, `chronic_health_status`, `is_elective_surgery`
输出：`RiskAssessment`（兼容 `risk_assessments` 写入格式，若触发告警同时返回 `AlertPayload`）

建议两个接口保持幂等，输出严格遵循 `TIMESTAMPTZ` 时间格式与数据库枚举约束。

七、测试要求

必须提供可运行的测试用例与种子数据，验证逻辑正确性：

Patient Memory Agent 至少 4 类 case：
1. 完整平稳流 → 验证滑动平均与 `stable` 趋势标签，`data_completeness_ratio` = 1.0
2. 高频波动流（如 `mean_arterial_pressure` 在 60-75 间震荡） → 验证 `volatility_index` 与 `fluctuating` 标签
3. 缺失值占比 30% 的数据（部分 `timestamp` 空缺） → 验证插值逻辑与 `data_completeness_ratio` 告警标记
4. 含多次 `intervention_events` 的时间轴 → 验证 `latest_interventions` 对齐与窗口切片边界

Risk Sentinel Agent 至少 4 类 case：
1. 标准 APACHE II 手动对照用例（提供已知 `vital_sign_events` 最差值，验证 `apache_ii_breakdown` 总分与子项得分完全匹配评分表）
2. 高危但干预 `responsive` → 验证 `urgency_adjusted=false`，`trend_direction` = `stabilizing`
3. 中危但干预 `deteriorating_despite_intervention` → 验证 `urgency_adjusted=true`，`severity` 提示上调
4. 缺省部分实验室指标（如无 `lab_type: creatinine`） → 验证缺失项默认 0 分且不影响总分计算，`confidence` < 1.0，`evidence` 链标记数据缺失

每个 case 建议附带 JSON 输入文件与预期输出文件，字段命名必须与《数据类型.md》100% 一致，后续可直接转为 pytest 用例或 `seed_test_data.py` 补充脚本。