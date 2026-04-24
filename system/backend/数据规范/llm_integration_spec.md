# LLM 接入规范 v1

## 1. 适用范围与前置约束

1. 本规范适用于 ICU 多智能体系统全部 agent 的 LLM 接入实现。
2. 本规范以 `agent_contract.md` 为唯一契约基线。
3. 本规范**禁止**修改现有 agent 输出 schema、事件类型与写库语义。
4. 现有 `rules.py` 规则链路必须保留，LLM 仅作为增强层。

---

## 2. 统一目录结构（强制）

所有 agent 的目录结构必须遵循以下模板：

```text
system/backend/app/agents/
  common/
    llm_client.py
    json_guard.py
    prompt_registry.py
    llm_types.py

  <agent_name>/
    contract.py
    llm.py
    rules.py
    service.py
    router.py
```

说明：

- `common/llm_client.py`：唯一允许触发外部 LLM API 的实现。
- `common/json_guard.py`：统一 JSON 解析与校验。
- `common/prompt_registry.py`：集中管理 prompt 版本。
- `contract.py`：agent 输入/输出契约常量，必须与 `agent_contract.md` 对齐。
- `llm.py`：agent 专属 prompt 装配与 llm 调用适配。
- `rules.py`：规则逻辑与 fallback 逻辑。
- `service.py`：读库、调用、写库、审计编排。
- `router.py`：API 暴露层。

---

## 3. LLM 调用入口（强制）

### 3.1 唯一调用路径

所有 LLM 调用必须经过：

- `system/backend/app/agents/common/llm_client.py`

任何 `service.py`、`rules.py`、`router.py` 中直接调用外部模型 SDK 或 HTTP 接口的行为，均视为违规。

### 3.2 统一函数签名

统一调用函数定义为：

```python
def run_llm_json(
    *,
    agent_name: str,
    prompt_version: str,
    system_prompt: str,
    input_payload: dict,
    output_contract: dict,
    timeout_sec: int = 30,
    max_retries: int = 2,
) -> dict:
    ...
```

参数约束：

- `agent_name`：必须与 contract 的 `AGENT_NAME` 一致。
- `prompt_version`：必须可在 `prompt_registry` 中追溯。
- `system_prompt`：必须包含 Role、Input、Output Contract 三部分。
- `input_payload`：结构化 JSON，不允许拼接非结构化原文日志。
- `output_contract`：用于 JSON 校验的契约定义，不可为空。
- `timeout_sec`：单次请求超时，默认 30 秒。
- `max_retries`：最大重试次数，默认 2 次。

返回约束：

- 返回值必须是**通过校验后的 JSON dict**。
- 失败场景由调用方按 fallback 机制处理，不得返回未校验对象。

---

## 4. Prompt 结构规范（强制）

每个 prompt 必须包含且仅包含以下三个逻辑部分：

1. `Role`
2. `Input`
3. `Output Contract`

推荐模板：

```text
[Role]
You are agent <agent_name> in ICU system. You perform bounded analysis only.

[Input]
<JSON serialized input_payload>

[Output Contract]
Return exactly one JSON object that matches <output_contract>.
```

输出限制（强制）：

- 仅允许输出合法 JSON。
- 禁止 markdown。
- 禁止代码块（如 ```json）。
- 禁止自然语言解释、前后缀说明、额外文本。

---

## 5. JSON 校验流程（强制）

所有模型原始响应必须执行以下顺序校验：

1. JSON 解析校验（可解析）
2. 顶层类型校验（必须为 object/dict）
3. `required fields` 校验
4. `enum` 校验
5. 数值范围校验（如置信度 0~1）
6. 额外字段校验（禁止未定义字段）
7. 可写库语义校验（字段类型与目标存储兼容）

若任一环节失败，必须触发失败处理流程，不得写入业务输出表。

---

## 6. 失败处理与降级（强制）

### 6.1 重试策略

- 最多重试 `max_retries` 次。
- 重试仍失败即进入 fallback。

### 6.2 fallback 规则

- fallback 必须调用 `rules.py` 的既有规则逻辑。
- fallback 输出仍需经过同一 JSON 校验流程。

### 6.3 orchestrator 状态

- LLM 失败但 fallback 成功：step 状态标记为 `degraded`。
- fallback 也失败：step 状态标记为 `error`。

> 说明：`degraded` 用于明确“主链路完成但 LLM 增强失败”。

---

## 7. 审计字段规范（强制）

每次 LLM 调用必须记录以下审计字段：

```json
{
  "agent_name": "risk_sentinel",
  "prompt_version": "risk_sentinel_v1",
  "input_payload": {},
  "raw_response": "...",
  "validated_output": {},
  "status": "success|degraded|error",
  "error": null,
  "latency_ms": 1234
}
```

字段定义：

- `agent_name`：调用方 agent
- `prompt_version`：prompt 版本号
- `input_payload`：输入快照
- `raw_response`：模型原始字符串
- `validated_output`：通过校验的 JSON
- `status`：执行状态
- `error`：错误描述（失败时必填）
- `latency_ms`：调用时延

---

## 8. 写库路径规范（强制）

LLM 调用后写库路径必须如下：

1. `validated_output` -> `agent_outputs`
2. `raw_response` 与 `validation_error` -> `audit_logs`
3. 完成事件 -> `agent_events`

要求：

- 未通过校验的输出不得进入 `agent_outputs`。
- `audit_logs` 必须保留可回放信息。
- `agent_events` 的 `event_type`、`schema_version` 必须与 `agent_contract.md` 一致。

---

## 9. 增强层定位（强制）

1. LLM 是增强层，不是唯一执行路径。
2. `rules.py` 必须保留并可独立运行。
3. 任意 agent 不得将规则逻辑删除为“纯 LLM 模式”。

---

## 10. 接入顺序（强制执行顺序）

接入顺序固定为：

1. `clinical_summary`
2. `risk_sentinel`
3. `patient_memory`
4. `intervention_tracker`
5. `bedside_monitor`
6. `ward_coordinator`

不得擅自调整顺序，除非发布新版本规范。

---

## 11. 与 Agent Contract 对齐规则

1. `output_type/event_type/schema_version` 必须复用 contract 常量。
2. LLM 输出字段不得超出 contract 定义。
3. 新增字段必须先更新 contract 与版本，再更新 LLM 层。
4. 同步更新 OpenAPI 与前端字段映射。

---

## 12. 合规检查清单（上线前）

每个 agent 接入完成后，必须通过以下检查：

1. 目录结构符合第 2 章。
2. 外部 LLM 调用仅存在于 `common/llm_client.py`。
3. prompt 包含 Role/Input/Output Contract。
4. 输出严格 JSON 且通过 7 步校验。
5. 失败重试 + fallback + degraded 标记生效。
6. 审计字段完整写入。
7. 写库路径符合第 8 章。
8. orchestrator 全流程回归通过。

---

## 13. 版本与生效

- 文档版本：`LLM Integration Spec v1`
- 生效方式：合并即生效
- 解释优先级：
  1. `agent_contract.md`
  2. 本文档
  3. agent 代码实现
