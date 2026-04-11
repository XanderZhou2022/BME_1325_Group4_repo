# 给代码助手的任务说明

我们现在开始实现 ICU 系统中属于**共享专家层（Shared Expert Layer）**的两个核心 Agent：Clinical Summary Agent 与 Ward Coordinator Agent。这一阶段的目标是构建能够聚合床位级结构化数据、生成临床可读摘要、并完成全局告警优先级排序的确定性模块。与第一层不同，这两个 Agent 不直接处理原始时序信号，而是**消费下游 Agent 的输出**，做信息压缩、逻辑归因与全局调度。

## 一、实现原则

这两个 agent 目前按**独立数据聚合与规则推理模块**实现，不依赖全局 Orchestrator，不接入实时消息队列，不调用 LLM 自由生成。
实现方式采用：

- Python
- FastAPI 接口
- Pydantic 数据模型
- 模板驱动 + 规则优先级计算
- 统一 JSON 输入/输出

目标是让它们成为未来多智能体协作链中的“信息收敛器”与“病房调度器”，现阶段通过模拟 JSON 数据独立验证逻辑。

------

## 二、Clinical Summary Agent 要做什么

Clinical Summary Agent 的职责是：
接收单床位各底层 Agent 的结构化输出，将其整合为面向医护的**24h 查房摘要**、**当前问题清单（Problem List）**与**今日关注重点**。它不是原始数据的复读机，而是临床信息的“翻译与重组器”。

### 输入

至少支持以下结构化字段（模拟来自 Bedside Monitor / Intervention Tracker / Risk Sentinel / Patient Memory 的输出）：

- `patient_id`, `bed_id`
- `vitals_summary`: 最近窗口内的异常标志、趋势标签、关键数值范围
- `intervention_responses`: 过去 24h 主要干预类型及响应评估（responsive / non-responsive 等）
- `active_risks`: 风险类型、置信度、证据摘要、紧急度分级
- `memory_context`: 主要诊断、未解决问题、最近转折点时间戳

输入形式建议为单次请求传入完整床位上下文 JSON。

### 输出

统一输出临床摘要结构：

- `patient_id`, `bed_id`, `generated_at`
- `24h_rounds_summary`: 结构化段落（背景 → 关键变化 → 当前状态）
- `problem_list`: 按优先级排序的活跃问题数组（含证据与状态标签）
- `focus_areas_for_today`: 今日需重点监测或复核的项目
- `clinical_narrative`: 面向查房的精炼叙述（模板+规则填充，非自由文本）

### 第一阶段分析逻辑

先采用**模板组装 + 规则排序**，不依赖生成式 LLM：

1. **问题去重与聚合**：若 Monitor 报 `persistent_hypotension` 且 Risk 报 `shock_risk: high`，合并为一条 `hemodynamic instability` 问题。
2. **干预-反应关联**：将 `intervention_responses` 与当前问题绑定，标记为“已干预/待评估/无响应”。
3. **优先级排序规则**：
   - Critical 风险 → 必列首位
   - `deteriorating_despite_intervention` → 次首位
   - 趋势 worsening → 中位
   - stable / info → 末位或仅归档
4. **摘要生成**：按固定临床句型拼接，例如：
   “过去24h主要围绕[问题1]与[问题2]进行干预。[干预A]后[指标B][改善/未改善/恶化]。当前核心矛盾为[未解决风险]，今日建议重点观察[监测项]。”

### 输出示例

```json
{
  "bed_id": "07",
  "24h_rounds_summary": "入ICU第3天，主因为感染性休克。过去12h血流动力学持续不稳，MAP维持在58-63 mmHg。",
  "problem_list": [
    {
      "problem": "持续性血流动力学不稳",
      "urgency": "critical",
      "evidence": "MAP连续6h<65，升压药需求上调",
      "intervention_status": "partially_responsive"
    },
    {
      "problem": "氧合波动",
      "urgency": "warning",
      "evidence": "SpO2在90-94%间波动，PEEP已调至10",
      "intervention_status": "monitoring"
    }
  ],
  "focus_areas_for_today": ["去甲肾上腺素滴定效果", "乳酸复查趋势", "潜在感染灶排查"],
  "generated_at": "2024-06-15T08:00:00Z"
}
```

------

## 三、Ward Coordinator Agent 要做什么

Ward Coordinator Agent 的职责是：
获取全病房（20床）的状态快照与告警，执行**告警去重、风暴抑制、优先级队列生成**，输出值班医护的**全局关注列表**。它解决的是"ICU 注意力资源有限，如何决定先看谁、先处理什么”的调度问题。

### 输入

- `ward_snapshot`: 数组，包含每张床的 `bed_id`, `current_urgency_level`, `active_risks`, `intervention_status`, `alert_flags`
- `alert_stream_window`: 过去 30min 内的原始告警事件列表（用于风暴检测）
- `staff_context` (可选): 当前值班医护数量（用于负载提示）

### 输出

统一输出病房级调度结构：

- `priority_queue`: 按优先级排序的床位列表（含综合风险分、首要问题、建议动作）
- `alert_storm_summary`: 合并后的告警簇（例如"Bed 03/05/09 同期报低氧告警，已聚合为设备/环境核查项”）
- `pending_actions`: 需立即人工复核或跨床位协调的事项
- `ward_load_indicator`: 轻/中/重负载提示

### 第一阶段分析逻辑

先做**确定性规则聚合**：

1. **告警风暴抑制**：
   - 同类告警 10min 内重复 >3 次 → 合并为 1 条，标记 `alert_flood_suppressed`
   - 跨床位相同设备参数异常 → 提示“疑似设备/网络故障”而非“患者恶化”
2. **优先级评分模型**：
   - 基础分：info=1, warning=3, critical=5
   - 叠加分：`deteriorating_despite_intervention` +2, `multiple_critical_risks` +2, `family_comms_pending` +1
   - 衰减分：`responsive` 且趋势改善 -2
3. **队列生成**：
   - Top-K 优先查房床位（按得分降序）
   - 标记 `requires_immediate_review` 的床位
   - 输出标准化调度建议，例如：“优先核查 Bed 12（干预后无改善）与 Bed 07（多系统风险），其余床位按常规巡视。”

### 输出示例

```json
{
  "priority_queue": [
    {"bed_id": "12", "score": 9, "primary_issue": "循环支持无响应", "action": "立即复核血流动力学"},
    {"bed_id": "07", "score": 7, "primary_issue": "感染恶化风险", "action": "复查炎症指标与培养"},
    {"bed_id": "03", "score": 4, "primary_issue": "氧合波动", "action": "调整呼吸机参数后观察"}
  ],
  "alert_storm_summary": {
    "detected": true,
    "merged_count": 14,
    "note": "Bed 01, 04, 09 同时报 SpO2 瞬降，已排除趋势恶化，提示可能为探头脱落/信号干扰"
  },
  "pending_actions": ["复核 Bed 12 升压药通道", "通知 Bed 05 家属沟通窗口已超 18h"],
  "ward_load_indicator": "high",
  "generated_at": "2024-06-15T08:05:00Z"
}
```

------

## 四、这两个 agent 先不要做什么

为避免初期过度设计，明确以下边界：

- 不做 LLM 自由文本生成（先保证结构稳定与可审计性）
- 不做真实事件总线/消息队列对接（先通过同步 JSON 请求模拟输入）
- 不做跨 Agent 动态路由或 Orchestrator 逻辑
- 不做家属沟通内容降维翻译（留给 Compassion Agent）
- 不做临床决策自动生成或治疗方案推荐
- 不做实时流式处理（先按批次/快照模式验证聚合逻辑）

这两个 Agent 属于系统的“信息收敛层”与“调度层”，当前阶段核心验证点是：**多源结构化输入能否正确归因、聚合、排序，并输出稳定可解析的临床/管理摘要。**

------

## 五、建议的目录结构

在现有 `backend/` 下新增共享专家层目录：

```text
backend/
  agents/
    clinical_summary/
      schemas.py          # 输入/输出 Pydantic 模型
      templates.py        # 临床摘要句型与问题排序规则
      service.py          # 核心聚合逻辑
      router.py           # FastAPI 路由
      examples.py         # 测试样例 JSON
    ward_coordinator/
      schemas.py
      scoring.py          # 优先级评分与风暴抑制规则
      service.py
      router.py
      examples.py
  api/
  数据规范/
  测试数据库/
```

------

## 六、接口建议

保持简洁的 RESTful 风格：

1. **Clinical Summary**
   `POST /agents/clinical-summary/generate`
   - 输入：单床位完整上下文 JSON（模拟底层 Agent 输出）
   - 输出：结构化查房摘要与问题清单

2. **Ward Coordinator**
   `POST /agents/ward-coordinator/triage`
   - 输入：全病房床位快照数组 + 告警窗口列表
   - 输出：优先级队列、告警聚合结果、负载提示

------

## 七、测试要求

必须提供覆盖典型 ICU 场景的测试用例，每个用例包含完整输入 JSON 与期望输出。

### Clinical Summary 测试用例（至少 4 类）
1. **稳定康复期**：多项指标趋稳，干预已 responsive，生成常规查房摘要。
2. **多系统恶化**：合并血流动力学不稳 + 氧合下降 + 乳酸上升，干预部分响应，正确排序问题并高亮未解决矛盾。
3. **术后监护**：以生命体征平稳为主，突出镇痛/引流/体温管理重点。
4. **边界模糊场景**：Monitor 报 warning 但 Intervention Tracker 显示已 responsive，验证摘要不夸大风险。

### Ward Coordinator 测试用例（至少 4 类）
1. **常规负载**：多数床位 info/warning，生成标准巡视队列。
2. **告警风暴抑制**：输入 20+ 条重复/瞬态告警，验证去重逻辑与 `alert_flood_suppressed` 标记。
3. **高危集中**：2-3 张床 critical + deteriorating，验证评分模型能否正确置顶并提示资源紧张。
4. **跨床位关联提示**：多床同类设备参数异常，输出“环境/设备核查”建议而非患者恶化队列。

---
**交付物要求**：
- 可运行的 FastAPI 服务（含两个路由）
- 完整的 Pydantic 模型定义
- 单元测试或独立测试脚本（覆盖上述用例，使用 `examples.py` 中的数据）
- 输出严格符合 JSON Schema 规范，便于后续接入 Orchestrator 与 LLM 增强层