# BME1325 全院统一接口契约 v1.0 · ICU（Group C）对齐说明

本文档描述本仓库相对《接口契约 v1.0》的实现位置与内部映射，供合规自检（§10）引用。

## 环境与 producer

| 变量 | 用途 |
|------|------|
| `HOSPITAL_REDIS_HOST` / `ICU_HOSPITAL_REDIS_HOST` | Redis Pub/Sub + Stream（§4） |
| `HOSPITAL_REDIS_PORT` / `HOSPITAL_REDIS_PASSWORD` | Redis 连接 |
| `DASHSCOPE_API_KEY` / `DASHSCOPE_MODEL` | **本地开发**：`api调用测试/.env`（与 `api使用.py` 一致，勿提交） |
| `ICU_LLM_ENABLED` | 后端是否启用 LLM（`system/backend/api/.env`） |
| `ICU_GROUP_PRODUCER` | 默认 `groupC.icu`（`config.group_producer`） |

未配置 Redis 时，事件发布为 no-op（开发机可照常启动）；教学联调环境必须配置。

## HTTP 响应外壳（§5.2）

除 `/health` 与 `/` 外，所有 `/api/v1/**` 成功响应由中间件包装为：

`{ "ok": true, "data": <路由返回值>, "error": null, "trace_id": "trc_..." }`

错误见全局异常处理器：`detail` 可为 `{ code, message, details }`（路由内 `HTTPException`）。

## ID 格式（§1）

| 实体 | 格式 | 生成/校验 |
|------|------|-----------|
| Patient | `P-{8 hex}` | `services/ids.new_patient_id`，路由正则校验 |
| Encounter | `E-{YYYYMMDDHHmmss}-{4 hex}` | `new_encounter_id` |
| Bed | `B-{病区}-{两位床号}` | 种子与 `format_bed_id` |
| 事件 ID | `evt_` + 26 位 `[0-9A-Z]` | `new_contract_event_id` |

## 内部状态 ↔ 全局 encounter_status（§2）

| `admissions.status`（内部） | `encounter_status`（对外） |
|------------------------------|----------------------------|
| `active`（在院） | `ADMITTED` |
| `discharged` | `DISCHARGED` |
| `expired` | `COMPLETED` |
| `transferred` | `TRANSFERRING` |

PATCH `/admissions/{id}/status` 会同步更新 `encounter_status`。

## 关键路由

- `POST /api/v1/encounters/{encounter_id}/transfer` — §6.1 接收方（`to_group` 需为 `groupC.icu`）；成功时发布 `patient.transferred`、`patient.admitted`（★ journal）。
- `POST /api/v1/admissions` — 与契约一致的入院创建；可带 `patient_profile` 做患者 upsert；发布 `patient.admitted`。
- 生命体征 POST 体支持附录 A.2 别名（`hr`/`map`/`sbp` 等）与内部 APACHE 字段名（`schemas.VitalSignEventCreate`）。

## Redis 与 agent_events

- `services/hospital_bus.publish_contract_event`：信封 §4.3，频道 `hospital.<event_type>`，★ 事件写入 `hospital:journal` Stream。
- `emit_agent_lifecycle_event` 在写入 `agent_events` 后镜像为 `alert.raised`（满足跨组可观测性；其它直接 INSERT 的 agent 行未全部覆盖，可后续抽公共函数）。

## LLM（本地：阿里云百炼 DashScope）

- **唯一配置**：`BME_1325_Group4_repo/api调用测试/.env`（`DASHSCOPE_API_KEY`、`DASHSCOPE_MODEL=qwen3.7-max`）。
- **唯一实现入口**：`system/llm/client.py` 的 `generate_structured_output()`（各 Agent 经此调用）；辅助 JSON 客户端见 `app/services/llm.py`。
- Base URL：`https://dashscope.aliyuncs.com/compatible-mode/v1`（OpenAI 兼容 `/chat/completions`）。
- 已弃用教学网 GenAI（`genaiapi.shanghaitech.edu.cn`）；勿再设置 `HOSPITAL_LLM_*` / `ICU_LLM_API_KEY` 指向该网关。
- `429` / 5xx 走重试与规则 fallback。

## 参考

- 课程权威文档：仓库外 `远程连接配置/接口契约_v1.0.md`（或教学组下发副本）。

## 契约迁移（Breaking change）

- 2026-05-08：种子与 API 使用契约型 ID；旧 `adm1` / `p1` / `b1` 已废弃。请重新执行 `init_core_tables.py` 与 `seed_test_data.py`。
