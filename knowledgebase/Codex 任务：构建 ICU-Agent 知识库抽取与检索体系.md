# Codex 任务：构建 ICU-Agent 知识库抽取与检索体系

请你阅读当前仓库：

```text
/Users/zhou/Desktop/Research/stimu2026/ICU_agent/BME_1325_Group4_repo
```

重点阅读：

```text
knowledgebase/original/
system/agents/
system/backend/
数据协议/
任务书/
```

当前 `knowledgebase/original/` 中已有 10 个 ICU/重症医学相关原始 PDF。请不要删除或移动这些原始 PDF。你的任务是基于这些 PDF，建立一套完整的、可供后续 agent 检索使用的 ICU 知识库体系。

## 一、总体目标

当前项目是一个 ICU 多智能体系统。后续 agent 需要根据不同任务检索知识库，而不是直接读取整篇 PDF。

请将原始 PDF 抽取为结构化知识卡，并建立可检索索引，使以下 agent 能够按需检索：

```text
Bedside Monitor Agent
Intervention Tracker Agent
Risk Sentinel Agent
Patient Memory Agent
Clinical Summary Agent
Ward Coordinator Agent
Compassion / Family Communication Agent
ICU Orchestrator Agent
```

知识库不能直接输出医疗决策。所有医学内容都必须标记：

```json
"human_review_required": true
```

知识库只用于：

```text
风险解释
证据背景
临床摘要
升级提醒
家属沟通草稿
规则校验
演示数据/benchmark 支持
```

禁止用于：

```text
自动诊断
自动治疗
自动给药
自动调整剂量
替代医生向家属宣布病情
```

------

# 二、请新增知识库目录结构

请在仓库中建立如下结构：

```text
knowledgebase/
  original/
    existing PDFs

  registry/
    sources.json
    extraction_status.json
    card_manifest.json

  schemas/
    source.schema.json
    guideline_card.schema.json
    computational_concept.schema.json
    retrieval_profile.schema.json

  extracted_text/
    <source_id>.txt
    <source_id>.pages.json

  cards/
    clinical_deterioration/
    triage_resource_allocation/
    padis_sedation_delirium/
    medication_safety/
    end_of_life_ethics/
    family_communication/
    icu_design_context/
    computational_concepts/
    general_icu_operations/

  indexes/
    cards.jsonl
    cards_minimal.jsonl
    bm25_index/
    vector_index/
    agent_retrieval_profiles.json

  scripts/
    kb_extract_text.py
    kb_build_sources_registry.py
    kb_generate_extraction_prompts.py
    kb_validate_cards.py
    kb_build_indexes.py
    kb_search_demo.py

  README.md
```

说明：

- `original/`：只放原始 PDF。
- `registry/`：记录每个 PDF 和每张 card 的元数据。
- `extracted_text/`：保存从 PDF 中抽出的纯文本和按页文本。
- `cards/`：保存结构化知识卡。
- `indexes/`：保存后续 agent 检索用的统一索引。
- `scripts/`：保存自动化抽取、校验、索引构建脚本。

------

# 三、第一步：建立 PDF 来源注册表

请扫描 `knowledgebase/original/` 下所有 PDF，并生成：

```text
knowledgebase/registry/sources.json
```

每个 PDF 一条记录，字段如下：

```json
{
  "source_id": "adult_icu_admission_triage_001",
  "filename": "xxx.pdf",
  "title": "Human readable title",
  "domain": "triage_resource_allocation",
  "population": "adult",
  "source_type": "clinical_guideline",
  "priority": "P1",
  "used_by_agents": [
    "WardCoordinatorAgent",
    "ClinicalSummaryAgent"
  ],
  "use_now": true,
  "human_review_required": true,
  "notes": "Short explanation of why this source is included."
}
```

## `domain` 只能从以下枚举中选择：

```text
clinical_deterioration
triage_resource_allocation
padis_sedation_delirium
medication_safety
end_of_life_ethics
family_communication
icu_design_context
computational_concepts
general_icu_operations
```

## `population` 只能从以下枚举中选择：

```text
adult
pediatric
mixed
general
```

## `source_type` 只能从以下枚举中选择：

```text
clinical_guideline
policy_statement
scoring_system
design_guideline
computational_reference
manual_reference
```

## `priority` 规则

请按以下规则自动或半自动标注：

```text
P0:
  直接服务当前 risk types 或核心 agent 运行逻辑的内容。

P1:
  对摘要、沟通、病房协调、用药安全、镇静谵妄等有用，但不是当前三个 risk types 的核心来源。

P2:
  项目背景、ICU 环境设计、PICU 暂不使用内容、伦理政策中暂不进入主检索的部分。
```

当前系统已有 risk types：

```text
persistent_shock_risk
respiratory_failure_risk
aki_risk
```

如果现有 PDF 没有直接覆盖 shock / ARDS / AKI，请不要强行标注为 P0。可以在 README 中记录“当前还缺少 sepsis/shock、ARDS/respiratory failure、AKI 的核心指南 PDF”。

------

# 四、第二步：抽取 PDF 文本

请实现：

```text
knowledgebase/scripts/kb_extract_text.py
```

要求：

1. 使用 `pymupdf` 或其他稳定 PDF 文本抽取工具。
2. 对每个 PDF 输出两个文件：

```text
knowledgebase/extracted_text/<source_id>.txt
knowledgebase/extracted_text/<source_id>.pages.json
```

`pages.json` 格式：

```json
{
  "source_id": "adult_icu_admission_triage_001",
  "pages": [
    {
      "page": 1,
      "text": "..."
    },
    {
      "page": 2,
      "text": "..."
    }
  ]
}
```

1. 不要用 OCR，除非文本抽取失败。
2. 如果某页文本为空，请在 `extraction_status.json` 中记录。
3. 文本抽取脚本不能修改原始 PDF。

------

# 五、第三步：设计统一知识卡 schema

请创建：

```text
knowledgebase/schemas/guideline_card.schema.json
```

每张临床知识卡必须符合以下字段：

```json
{
  "card_id": "clinical_deterioration_persistent_abnormal_vitals_001",
  "source_id": "source id from sources.json",
  "source_title": "source title",
  "domain": "clinical_deterioration",
  "subdomain": "rapid_response",
  "population": "adult",
  "card_type": "guideline_context",
  "topic": "Persistent abnormal vital signs",
  "clinical_context": "When a patient shows sustained abnormal vital signs or worsening trend.",
  "key_points": [
    "Short, faithful, non-hallucinated point extracted from source.",
    "Another point."
  ],
  "trigger_signals": [
    "persistent hypotension",
    "worsening oxygenation",
    "decreased urine output"
  ],
  "related_risk_types": [
    "persistent_shock_risk",
    "respiratory_failure_risk",
    "aki_risk"
  ],
  "used_by_agents": [
    "RiskSentinelAgent",
    "ClinicalSummaryAgent"
  ],
  "allowed_use": [
    "risk explanation",
    "clinical summary",
    "human review escalation wording"
  ],
  "forbidden_use": [
    "automatic diagnosis",
    "treatment order",
    "drug dose recommendation"
  ],
  "retrieval_keywords": [
    "deterioration",
    "vital signs",
    "rapid response",
    "escalation"
  ],
  "evidence_location": {
    "page_start": 10,
    "page_end": 12,
    "section_title": "if available",
    "quote": "Short exact quote from the source, maximum 1-2 sentences."
  },
  "confidence": "high",
  "human_review_required": true,
  "last_updated": "YYYY-MM-DD"
}
```

## `card_type` 枚举

```text
guideline_context
risk_background
escalation_principle
communication_principle
ethical_policy
medication_safety_context
scoring_context
icu_operations_context
design_context
```

------

# 六、第四步：另外建立 computational concept schema

请创建：

```text
knowledgebase/schemas/computational_concept.schema.json
```

用于 APACHE II、评分系统、后续 SOFA、Sepsis-3、MIMIC concepts。

格式：

```json
{
  "concept_id": "apache_ii_overview_001",
  "source_id": "msd_critical_illness_scoring_001",
  "concept_name": "APACHE II",
  "domain": "computational_concepts",
  "concept_type": "severity_score",
  "purpose": "Describe severity of illness / mortality risk context.",
  "inputs": [
    "temperature",
    "mean arterial pressure",
    "heart rate",
    "respiratory rate",
    "oxygenation",
    "arterial pH",
    "serum sodium",
    "serum potassium",
    "serum creatinine",
    "hematocrit",
    "white blood cell count",
    "Glasgow Coma Scale",
    "age",
    "chronic health points"
  ],
  "outputs": [
    "severity score"
  ],
  "used_by_agents": [
    "RiskSentinelAgent",
    "ClinicalSummaryAgent",
    "WardCoordinatorAgent"
  ],
  "allowed_use": [
    "score explanation",
    "dashboard context",
    "benchmark support"
  ],
  "forbidden_use": [
    "direct clinical decision",
    "automatic prognosis announcement"
  ],
  "evidence_location": {
    "page_start": 1,
    "page_end": 3,
    "section_title": "if available",
    "quote": "Short exact quote."
  },
  "human_review_required": true
}
```

------

# 七、第五步：按 agent 设计抽取知识卡

不要按 PDF 机械切 chunk。请按 agent 的使用场景抽取。

## 1. Bedside Monitor Agent 需要的卡

用途：解释生命体征异常和趋势变化。

请抽取卡片类型：

```text
persistent_abnormal_vitals_context
worsening_trend_context
hypoxemia_context
hypotension_context
tachypnea_context
decreased_urine_output_context
clinical_deterioration_context
```

每张卡要包含：

```text
trigger_signals
time_window_hint
clinical_context
allowed_summary_language
human_review_required
```

例子：

```json
{
  "card_id": "clinical_deterioration_worsening_trend_001",
  "domain": "clinical_deterioration",
  "card_type": "escalation_principle",
  "topic": "Worsening clinical trend",
  "trigger_signals": [
    "sustained abnormal vital signs",
    "new deterioration",
    "failure to improve after intervention"
  ],
  "used_by_agents": [
    "BedsideMonitorAgent",
    "RiskSentinelAgent"
  ]
}
```

## 2. Risk Sentinel Agent 需要的卡

用途：支持风险解释，而不是诊断。

当前 risk types：

```text
persistent_shock_risk
respiratory_failure_risk
aki_risk
```

请为每个 risk type 抽取或建立可检索背景卡。

即使当前 PDF 不能直接覆盖 sepsis/shock/ARDS/AKI，也要从现有 PDF 中抽取“通用恶化识别、升级提醒、评分系统、用药安全、资源分配”相关内容，并在 card 中标注：

```json
"direct_risk_source": false
```

字段建议增加：

```json
{
  "related_risk_types": [
    "persistent_shock_risk"
  ],
  "direct_risk_source": false,
  "risk_use_note": "This card provides general deterioration/escalation context, not disease-specific shock guideline."
}
```

## 3. Intervention Tracker Agent 需要的卡

用途：解释“干预后是否改善”“用药/治疗事件需要复核”。

请重点从 ICU 安全用药指南、恶化识别指南中抽取：

```text
intervention_response_monitoring
medication_safety_review
high_risk_medication_context
renal_function_medication_context
treatment_after_deterioration_context
```

卡片要包含：

```text
intervention_types
observation_targets
response_language
forbidden_use
```

禁止生成具体剂量或医嘱。

## 4. Patient Memory Agent 需要的卡

用途：帮助 Patient Memory 把事件写成长期病程语义。

请抽取：

```text
major_deterioration_event
unresolved_problem_context
communication_event_context
ethical_conflict_context
sedation_delirium_context
```

卡片要支持这些 memory tags：

```text
deterioration
intervention_response
sedation_status
delirium_context
family_communication
ethical_decision
triage_priority
```

## 5. Clinical Summary Agent 需要的卡

用途：生成医生/护士看的 ICU 摘要。

请抽取：

```text
round_summary_context
problem_list_context
clinical_deterioration_summary
medication_safety_summary
sedation_delirium_summary
triage_status_summary
end_of_life_summary_context
```

卡片要包含：

```text
professional_summary_template
allowed_terms
avoid_terms
human_review_required
```

## 6. Ward Coordinator Agent 需要的卡

用途：全 ICU 20 床优先级排序、告警去重、资源分配、分诊原则。

请从 admission/discharge/triage、资源分配、快速反应系统中抽取：

```text
icu_admission_priority
icu_discharge_readiness
triage_principles
scarce_resource_allocation
rapid_response_escalation
ward_level_prioritization
```

卡片要包含：

```text
priority_factors
resource_context
fairness_or_ethics_note
forbidden_use
```

禁止 agent 自动决定谁进 ICU、谁出 ICU、谁不治疗。只能支持“排序提醒”和“人工复核”。

## 7. Compassion / Family Communication Agent 需要的卡

用途：家属版摘要、ICU diary、人文沟通草稿。

请从 PADIS、终末期照护、伦理政策、family communication 相关内容中抽取：

```text
family_friendly_explanation
why_patient_cannot_communicate
sedation_family_explanation
delirium_family_explanation
end_of_life_communication
shared_decision_making
potentially_inappropriate_treatment_conflict
clinician_approval_required
```

每张卡必须包含：

```json
{
  "requires_clinician_approval": true,
  "not_for_direct_family_delivery": true
}
```

卡片应包含：

```text
family_friendly_language
professional_preview_language
phrases_to_avoid
```

禁止输出：

```text
definitive prognosis
treatment withdrawal recommendation
futility judgment
```

------

# 八、第六步：建立 agent retrieval profiles

请创建：

```text
knowledgebase/indexes/agent_retrieval_profiles.json
```

内容如下：

```json
{
  "BedsideMonitorAgent": {
    "allowed_domains": [
      "clinical_deterioration",
      "padis_sedation_delirium",
      "computational_concepts"
    ],
    "preferred_card_types": [
      "guideline_context",
      "escalation_principle",
      "risk_background"
    ],
    "forbidden_domains": [
      "end_of_life_ethics",
      "icu_design_context"
    ],
    "default_top_k": 5
  },
  "RiskSentinelAgent": {
    "allowed_domains": [
      "clinical_deterioration",
      "medication_safety",
      "computational_concepts",
      "triage_resource_allocation"
    ],
    "preferred_card_types": [
      "risk_background",
      "escalation_principle",
      "scoring_context",
      "medication_safety_context"
    ],
    "forbidden_domains": [
      "icu_design_context"
    ],
    "default_top_k": 8
  },
  "InterventionTrackerAgent": {
    "allowed_domains": [
      "medication_safety",
      "clinical_deterioration",
      "padis_sedation_delirium",
      "computational_concepts"
    ],
    "preferred_card_types": [
      "medication_safety_context",
      "guideline_context",
      "escalation_principle"
    ],
    "default_top_k": 6
  },
  "PatientMemoryAgent": {
    "allowed_domains": [
      "clinical_deterioration",
      "padis_sedation_delirium",
      "family_communication",
      "end_of_life_ethics",
      "triage_resource_allocation"
    ],
    "preferred_card_types": [
      "guideline_context",
      "communication_principle",
      "ethical_policy"
    ],
    "default_top_k": 6
  },
  "ClinicalSummaryAgent": {
    "allowed_domains": [
      "clinical_deterioration",
      "medication_safety",
      "padis_sedation_delirium",
      "triage_resource_allocation",
      "end_of_life_ethics",
      "computational_concepts"
    ],
    "preferred_card_types": [
      "guideline_context",
      "risk_background",
      "scoring_context",
      "medication_safety_context"
    ],
    "default_top_k": 8
  },
  "WardCoordinatorAgent": {
    "allowed_domains": [
      "triage_resource_allocation",
      "clinical_deterioration",
      "end_of_life_ethics",
      "computational_concepts"
    ],
    "preferred_card_types": [
      "escalation_principle",
      "ethical_policy",
      "icu_operations_context",
      "scoring_context"
    ],
    "default_top_k": 8
  },
  "CompassionAgent": {
    "allowed_domains": [
      "family_communication",
      "padis_sedation_delirium",
      "end_of_life_ethics"
    ],
    "preferred_card_types": [
      "communication_principle",
      "ethical_policy",
      "guideline_context"
    ],
    "forbidden_domains": [
      "medication_safety",
      "icu_design_context"
    ],
    "default_top_k": 6,
    "requires_clinician_approval": true
  }
}
```

------

# 九、第七步：构建统一检索索引

请实现：

```text
knowledgebase/scripts/kb_build_indexes.py
```

输出：

```text
knowledgebase/indexes/cards.jsonl
knowledgebase/indexes/cards_minimal.jsonl
knowledgebase/indexes/bm25_index/
```

每张 card 在 `cards.jsonl` 中占一行。

`cards_minimal.jsonl` 用于快速检索，字段只保留：

```json
{
  "card_id": "",
  "domain": "",
  "topic": "",
  "key_points": [],
  "trigger_signals": [],
  "related_risk_types": [],
  "used_by_agents": [],
  "retrieval_keywords": [],
  "human_review_required": true
}
```

请先实现 BM25 / keyword 检索，不要求必须实现 embedding。后续如果项目已有 embedding 或 Chroma/Faiss，再接入 vector index。

------

# 十、第八步：实现检索 demo

请实现：

```text
knowledgebase/scripts/kb_search_demo.py
```

支持命令行：

```bash
python knowledgebase/scripts/kb_search_demo.py \
  --agent RiskSentinelAgent \
  --query "persistent hypotension after fluid bolus, possible shock risk" \
  --risk_type persistent_shock_risk \
  --top_k 5
```

输出格式：

```json
{
  "agent": "RiskSentinelAgent",
  "query": "...",
  "filters": {
    "risk_type": "persistent_shock_risk"
  },
  "results": [
    {
      "card_id": "...",
      "domain": "...",
      "topic": "...",
      "score": 12.4,
      "key_points": [],
      "allowed_use": [],
      "forbidden_use": [],
      "evidence_location": {}
    }
  ]
}
```

检索必须应用 `agent_retrieval_profiles.json`：

- 只能检索该 agent allowed domains。
- 避免 forbidden domains。
- 根据 risk_type 优先召回相关卡。
- CompassionAgent 必须只召回 family / PADIS / ethics 相关内容。

------

# 十一、第九步：质量检查与验证

请实现：

```text
knowledgebase/scripts/kb_validate_cards.py
```

检查内容：

1. 每张 card 必须符合 schema。
2. 每张 card 必须有 `source_id`。
3. 每张 card 必须能在 `sources.json` 中找到对应 source。
4. 每张 card 必须有 `evidence_location`。
5. 每张 card 必须有 `allowed_use` 和 `forbidden_use`。
6. 每张医学/伦理/沟通卡必须：

```json
"human_review_required": true
```

1. Pediatric/PICU 来源不能默认进入 adult ICU agent 的检索 profile。
2. ICU design guideline 不能被 RiskSentinelAgent 默认检索。
3. CompassionAgent 的 card 必须包含：

```json
"requires_clinician_approval": true
```

1. 如果卡片没有精确证据页码，`confidence` 必须设为 `"low"`，并在 `notes` 中说明。

------

# 十二、第十步：抽取策略要求

请不要把 PDF 简单切成 500-token chunk 后直接入库。请执行“知识卡抽取”。

每张 card 应该满足：

```text
一张 card 只表达一个知识点
每张 card 可以被单独检索和引用
每张 card 有明确 agent 使用对象
每张 card 有明确 forbidden_use
每张 card 有 evidence_location
每张 card 不包含长篇原文
每张 card 不伪造指南内容
```

如果使用 LLM 辅助抽取，请生成 prompt 文件，但不要在代码中硬编码 API key。

请创建：

```text
knowledgebase/prompts/
  extract_guideline_cards.md
  extract_computational_concepts.md
  extract_agent_retrieval_keywords.md
```

其中 `extract_guideline_cards.md` 要求 LLM 输出严格 JSON，并强调：

```text
Only extract information explicitly supported by the provided source text.
Do not invent recommendations.
Do not generate medication dose recommendations.
Do not generate direct treatment orders.
Every card must include evidence_location.
Every card must include forbidden_use.
Every card must set human_review_required=true.
```

------



------

# 十四、必须在 README 中写清楚的内容

请创建或更新：

```text
knowledgebase/README.md
```

内容包括：

```text
1. knowledgebase/original 是原始 PDF 来源目录。
2. cards/ 是结构化知识卡目录。
3. registry/sources.json 记录每个 PDF 的来源和使用限制。
4. indexes/ 是 agent 检索入口。
5. 本知识库仅用于 ICU agent 的风险解释、摘要、沟通草稿和人工复核提醒。
6. 本知识库不能用于自动诊断、自动治疗或自动给药。
7. 所有 clinical/ethical/family communication 输出必须 human-in-the-loop。
8. 当前知识库已有 ICU workflow/safety/ethics/scoring/design 资料。
9. 当前仍建议补充 sepsis/shock、ARDS/respiratory failure、AKI 的核心指南来源，以更好覆盖 persistent_shock_risk、respiratory_failure_risk、aki_risk。
10. 后续 agent 应通过 retrieval profile 检索 cards，而不是直接读取原始 PDF。
```

------

# 十五、最终交付物

请完成后保证以下文件存在：

```text
knowledgebase/registry/sources.json
knowledgebase/registry/extraction_status.json
knowledgebase/registry/card_manifest.json

knowledgebase/schemas/source.schema.json
knowledgebase/schemas/guideline_card.schema.json
knowledgebase/schemas/computational_concept.schema.json
knowledgebase/schemas/retrieval_profile.schema.json

knowledgebase/extracted_text/*.txt
knowledgebase/extracted_text/*.pages.json

knowledgebase/cards/**/*.json

knowledgebase/indexes/cards.jsonl
knowledgebase/indexes/cards_minimal.jsonl
knowledgebase/indexes/agent_retrieval_profiles.json

knowledgebase/scripts/kb_extract_text.py
knowledgebase/scripts/kb_build_sources_registry.py
knowledgebase/scripts/kb_generate_extraction_prompts.py
knowledgebase/scripts/kb_validate_cards.py
knowledgebase/scripts/kb_build_indexes.py
knowledgebase/scripts/kb_search_demo.py

knowledgebase/prompts/extract_guideline_cards.md
knowledgebase/prompts/extract_computational_concepts.md
knowledgebase/prompts/extract_agent_retrieval_keywords.md

knowledgebase/README.md
```

------

# 十六、验收测试

请确保以下命令可以运行：

```bash
python knowledgebase/scripts/kb_extract_text.py
python knowledgebase/scripts/kb_build_sources_registry.py
python knowledgebase/scripts/kb_validate_cards.py
python knowledgebase/scripts/kb_build_indexes.py
python knowledgebase/scripts/kb_search_demo.py --agent RiskSentinelAgent --query "patient has persistent hypotension and worsening trend" --risk_type persistent_shock_risk --top_k 5
python knowledgebase/scripts/kb_search_demo.py --agent CompassionAgent --query "explain to family why the patient cannot communicate after sedation" --top_k 5
python knowledgebase/scripts/kb_search_demo.py --agent WardCoordinatorAgent --query "ICU bed priority and triage during resource limitation" --top_k 5
```

每个 demo 输出必须包含：

```text
card_id
domain
topic
key_points
evidence_location
allowed_use
forbidden_use
human_review_required
```

------

# 十七、特别注意

请不要做以下事情：

```text
不要删除 original PDF
不要把所有 PDF 直接切 chunk 当知识库
不要让 pediatric/PICU 内容默认进入 adult ICU agent
不要让 ICU design guideline 进入 Risk Sentinel 的默认检索
不要生成药物剂量建议
不要生成治疗方案
不要生成诊断结论
不要让 Compassion Agent 直接面向家属输出未经医生确认的内容
不要在代码里写 API key
不要伪造页码、章节或来源
```

最终目标是：建立一个**结构化、可审计、按 agent 功能分层、可检索、可安全扩展**的 ICU-Agent 知识库，而不是普通 PDF RAG。