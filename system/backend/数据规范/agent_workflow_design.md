# ICU 多智能体系统工作逻辑设计 v1

## 1. 设计目标

本系统不是“对话式医疗 AI”，而是一个以 ICU 高频时序数据为核心的事件驱动系统。患者状态主要来自生命体征、实验室检查、治疗干预和病程事件，agent 的任务是在这些数据进入系统后，完成状态判断、干预响应评估、时序记忆更新、风险识别、临床摘要和病区级调度。

系统总体原则是：

```text
外部事件进入数据库
→ orchestrator 判断事件类型
→ 触发对应 agent
→ agent 读取数据库上下文
→ 生成结构化输出
→ 写回数据库
→ 下游 agent 基于新状态继续运行
```

这与项目最初设定的“事件触发 agent 运行 → 更新状态 → 输出结果”的机制一致，同时也符合 ICU 场景中“持续感知患者状态变化、基于历史数据进行风险判断、协调多角色信息流”的目标。

---

## 2. 核心设计原则

### 2.1 Agent 不直接互相私聊

系统中 agent 之间不应通过自由文本互相调用，而是通过数据库和事件总线协作。

也就是说：

```text
Agent A 不直接把消息发给 Agent B
Agent A 写入 agent_outputs / agent_events / patient_state_current
Orchestrator 或调度器根据这些结果触发 Agent B
Agent B 再从数据库读取最新上下文
```

这样设计的原因是：

1. 所有状态可回放；
2. 所有输出可审计；
3. 下游 agent 不依赖上游函数调用细节；
4. 前端 showcase 可以直接读取数据库展示完整过程；
5. 未来接入 LLM 后，失败、重试、降级都更容易控制。

原始架构中也建议采用共享患者状态板，而不是 agent 之间自由聊天：Bedside Monitor 写入生命体征摘要，Intervention Tracker 写入干预与反应，Risk Sentinel 写入风险列表，Patient Memory 写入病程记忆，Clinical Summary 和 Ward Coordinator 再读取这些共享状态进行汇总。

---

## 3. Agent 类型划分

本系统中的 agent 按触发方式分为三类。

### 3.1 事件触发型 Agent

这类 agent 由外部新事件直接触发。

包括：

```text
bedside_monitor
intervention_tracker
```

它们的特点是：

```text
有新 vitals / intervention 才运行
运行范围通常是单患者
输出是局部状态判断
```

---

### 3.2 状态跟随型 Agent

这类 agent 不直接依赖前端事件，而是跟随上游 agent 的输出更新。

包括：

```text
patient_memory
risk_sentinel
clinical_summary
```

它们的特点是：

```text
读取上游 agent 输出
整合患者当前状态
生成更高层次的病程记忆、风险判断或临床摘要
```

---

### 3.3 全局巡检型 Agent

这类 agent 面向整个 ICU 病区运行。

包括：

```text
ward_coordinator
```

它的特点是：

```text
读取所有 active admissions
比较所有患者风险与状态
生成病区级优先队列和资源调度建议
```

Ward Coordinator 的原始定位就是从全局视角比较 20 张床的风险优先级、处理告警风暴、生成护士站或值班医生关注列表。

---

## 4. 外部输入事件

系统目前重点接收两类外部事件。

### 4.1 生命体征事件 vitals

来源：

```text
前端客户端
自动定时发送机器
模拟数据生成器
```

写入位置：

```text
events
vital_sign_events
patient_state_current.current_vitals
```

典型字段：

```text
HR
MAP
SBP / DBP
RR
Temp
SpO2
FiO2
PaO2
pH
GCS
timestamp
```

触发 agent：

```text
bedside_monitor
```

---

### 4.2 治疗干预事件 interventions

来源：

```text
前端客户端
护士/医生操作模拟器
自动场景脚本
```

写入位置：

```text
events
intervention_events
patient_state_current.latest_interventions
```

典型类型：

```text
fluid
vasopressor
ventilator_change
```

触发 agent：

```text
intervention_tracker
```

---

### 4.3 可扩展事件

后续可以扩展：

```text
lab
admission
discharge
transfer
round_event
family_update_request
manual_review_request
```

其中 admission、discharge、transfer 会直接影响 ward_coordinator，因为它们改变了病区床位和资源状态。

---

## 5. 单患者核心工作流

### 5.1 vitals 事件链

当系统收到某患者新的生命体征数据时，流程如下：

```text
Step 1: 客户端/定时机器发送 vitals
Step 2: 后端写入 events + vital_sign_events
Step 3: orchestrator 识别 event_type = vital_sign
Step 4: 触发 bedside_monitor
Step 5: bedside_monitor 读取最近时间窗 vitals
Step 6: bedside_monitor 生成状态判断
Step 7: bedside_monitor 写入 agent_outputs / agent_events
Step 8: patient_memory 被触发，更新时序记忆
Step 9: risk_sentinel 根据新 memory 和 bedside 输出判断风险
Step 10: clinical_summary 视情况更新摘要
Step 11: 如果风险达到 warning/critical，触发 ward_coordinator 更新全局队列
```

bedside_monitor 的核心作用是把原始数值转换为结构化临床状态摘要，例如从单个 MAP 数值转成“过去 90 分钟 MAP 持续下降，当前低于目标阈值”。

---

### 5.2 intervention 事件链

当系统收到某患者新的治疗干预时，流程如下：

```text
Step 1: 客户端/操作模拟器发送 intervention
Step 2: 后端写入 events + intervention_events
Step 3: orchestrator 识别 event_type = intervention
Step 4: 触发 intervention_tracker
Step 5: intervention_tracker 登记干预事件
Step 6: intervention_tracker 判断是否已有足够后续观察数据
Step 7a: 如果观察窗口不足，输出 pending 状态
Step 7b: 如果观察窗口足够，评估 response
Step 8: 写入 agent_outputs / agent_events
Step 9: patient_memory 更新近期关键干预与响应
Step 10: risk_sentinel 重新评估风险
Step 11: clinical_summary 视情况更新
Step 12: 如果干预后仍恶化，触发 ward_coordinator 更新优先队列
```

这里最重要的是：intervention_tracker 不应该只在干预发生时运行一次。因为干预效果需要观察窗口。

推荐逻辑是：

```text
intervention 到达时：
    创建 pending_intervention

观察窗口结束时：
    重新运行 intervention_tracker
    对比干预前后指标
    输出 responsive / partially_responsive / non_responsive / deteriorated
```

Intervention Tracker 的原始定位就是追踪“做了什么治疗，以及做完以后有没有变化”，把 ICU 分析从单点监测推进到“动作—结果—再评估”的因果链。

---

## 6. 各 Agent 工作逻辑

## 6.1 bedside_monitor

### 定位

单患者、事件触发型 agent。

负责读取患者最近一段时间窗内生命体征，判断床旁状态。

### 触发条件

```text
1. 新 vital_sign_events 写入；
2. orchestrator demo-run 指定运行；
3. 人工点击单患者 run；
4. 可选：定时巡检时发现 vitals 长时间未分析。
```

### 读取数据

```text
patients
admissions
beds
vital_sign_events
lab_events，可选
intervention_events，可选
patient_state_current
```

### 推荐时间窗

```text
短窗口：最近 30-90 分钟，用于即时异常；
中窗口：最近 6 小时，用于趋势判断；
长窗口：最近 24 小时，只用于比较背景，不做每次重算。
```

### 核心判断

```text
1. 当前指标是否异常；
2. 异常是否持续；
3. 是否出现恶化趋势；
4. 是否存在明显波动；
5. 是否达到 warning / critical。
```

### 输出内容

```text
abnormal_flags
trend_labels
evidence
urgency_level
current_status_summary
```

### 写库

```text
agent_outputs：完整 bedside 输出
agent_events：bedside_monitor.completed
patient_state_current.current_vitals：当前生命体征摘要
patient_state_current.care_phase：必要时更新 stable / unstable / critical
audit_logs：输入窗口、输出、运行状态
```

### 下游触发

```text
patient_memory：每次 bedside 完成后触发
risk_sentinel：如果 urgency_level 为 warning/critical，可立即触发
clinical_summary：如果出现新 critical 状态，可延迟触发或按需触发
```

---

## 6.2 intervention_tracker

### 定位

单患者、事件触发 + 延迟评估型 agent。

负责围绕一次干预事件，评估干预前后患者状态变化。

### 触发条件

```text
1. 新 intervention_events 写入；
2. pending intervention 到达观察窗口结束时间；
3. 新 vitals/lab 到达后发现存在未评估 intervention；
4. orchestrator demo-run 指定运行。
```

### 读取数据

```text
intervention_events
vital_sign_events
lab_events
bedside_monitor outputs
patient_state_current
```

### 推荐观察窗口

不同干预类型应使用不同观察窗口：

```text
fluid：
    前窗口：干预前 30-60 分钟
    后窗口：干预后 30-120 分钟

vasopressor：
    前窗口：调整前 30-60 分钟
    后窗口：调整后 15-90 分钟

ventilator_change：
    前窗口：调整前 30-60 分钟
    后窗口：调整后 30-120 分钟

lab-response：
    乳酸、肌酐等实验室指标可使用 2-6 小时窗口
```

### 核心判断

```text
1. 干预前状态；
2. 干预后状态；
3. 关键指标是否改善；
4. 改善是否足够；
5. 是否出现干预后仍恶化；
6. 是否需要升级关注。
```

### 响应类型

```text
responsive
partially_responsive
non_responsive
deteriorated
pending_insufficient_data
```

### 写库

```text
agent_outputs：完整 intervention response
agent_events：intervention_tracker.completed 或 intervention_tracker.pending
patient_state_current.latest_interventions：最近干预摘要
audit_logs：干预事件、前后窗口、输出、运行状态
```

### 下游触发

```text
patient_memory：每次 completed 或 pending 更新后触发
risk_sentinel：如果 non_responsive / deteriorated，立即触发
clinical_summary：如果重要干预有明确响应结果，可触发更新
```

---

## 6.3 patient_memory

### 定位

单患者、状态跟随型 agent。

负责把近期 vitals/lab/intervention/agent_outputs 汇总为患者时序记忆快照。

### 触发条件

```text
1. bedside_monitor completed；
2. intervention_tracker completed；
3. lab_events 写入；
4. risk_sentinel completed 后需要回写风险记忆；
5. 定时刷新，例如每 15-30 分钟；
6. orchestrator demo-run 指定运行。
```

### 读取数据

```text
patient_state_current
vital_sign_events
lab_events
intervention_events
agent_outputs from bedside_monitor
agent_outputs from intervention_tracker
agent_outputs from risk_sentinel，可选
previous patient_state_snapshots
```

### 推荐记忆窗口

```text
短期记忆：最近 1-6 小时
中期记忆：最近 24 小时
长期记忆：入 ICU 以来或最近 72 小时摘要
```

这个设计与原始任务书中的 temporal memory 机制一致：每个 patient 需要维护短期窗口、中期窗口和长期窗口，避免 agent 只看当前数值。

### 核心处理

```text
1. 当前指标快照；
2. 趋势向量；
3. 波动度；
4. 近期关键干预；
5. 最近风险变化；
6. 数据完整度；
7. unresolved problems；
8. 当前最需要关注的问题。
```

### 写库

```text
patient_state_snapshots：完整 memory snapshot
patient_state_current.active_problems：当前问题列表
patient_state_current.latest_interventions：关键干预摘要
patient_state_current.updated_at：更新时间
agent_outputs：memory 输出
agent_events：patient_memory.completed
audit_logs：读取范围、输出、状态
```

### 下游触发

```text
risk_sentinel：memory 更新后触发
clinical_summary：如果 active_problems 有变化，可触发
ward_coordinator：一般不直接触发，除非 care_phase 变化
```

---

## 6.4 risk_sentinel

### 定位

单患者、状态跟随 + 周期巡检型 agent。

负责消费 bedside、intervention、patient_memory 的结果，识别临床风险并产出告警。

### 触发条件

```text
1. patient_memory completed；
2. bedside_monitor 输出 warning/critical；
3. intervention_tracker 输出 non_responsive/deteriorated；
4. 新 lab_events 到达，例如 lactate 升高；
5. 固定周期巡检，例如每 5-15 分钟；
6. orchestrator demo-run 指定运行。
```

### 读取数据

```text
patient_state_current
patient_state_snapshots
risk_assessments history
alerts
agent_outputs from bedside_monitor
agent_outputs from intervention_tracker
agent_outputs from patient_memory
lab_events
```

### 核心风险类型

```text
shock
respiratory_failure
persistent_hypoperfusion
sepsis_worsening
aki_risk
hemodynamic_instability
post_intervention_deterioration
```

### 核心判断

```text
1. 当前是否存在 active risk；
2. 风险是否新出现；
3. 风险是否升级；
4. 风险是否持续；
5. 是否已有干预但仍无改善；
6. 是否需要生成或更新 alert。
```

### 输出内容

```text
risk_type
confidence
severity
evidence
time_window
recommended_action
escalation_level
```

Risk Sentinel 在原始设计中被定义为最接近临床推理的一层，但它输出的是风险画像，而不是最终诊断或治疗决定。

### 写库

```text
risk_assessments：每次风险评估记录
alerts：open / update / close 告警
patient_state_current.active_risks：当前风险列表
patient_state_current.care_phase：必要时更新
agent_outputs：risk_sentinel 输出
agent_events：risk_sentinel.completed
audit_logs：输入、输出、风险变化
```

### 下游触发

```text
clinical_summary：risk 变化后触发
ward_coordinator：warning/critical 或 alert 状态变化后触发
```

---

## 6.5 clinical_summary

### 定位

单患者、状态跟随 + 按需生成型 agent。

负责整合 bedside、intervention、memory、risk 信息，生成 24h 临床摘要、问题清单、今日关注点和临床叙事。

### 触发条件

```text
1. risk_sentinel completed 且风险发生变化；
2. patient_memory active_problems 发生变化；
3. 每 6 小时生成一次简短摘要；
4. 每 24 小时生成查房摘要；
5. 医生打开单患者详情页时按需生成；
6. orchestrator demo-run 指定运行。
```

### 读取数据

```text
patient_state_current
patient_state_snapshots
risk_assessments
alerts
agent_outputs from bedside_monitor
agent_outputs from intervention_tracker
agent_outputs from patient_memory
agent_outputs from risk_sentinel
admissions
```

### 推荐生成频率

```text
事件触发摘要：只在重要变化后生成；
6h 摘要：用于单患者详情页；
24h 摘要：用于查房；
按需摘要：用于前端展示和医生查看。
```

### 核心输出

```text
24h clinical summary
problem list
today_focus
clinical_narrative
recent_changes
risk_summary
intervention_response_summary
```

Clinical Summary 的原始定位是把复杂 ICU 数据整理为面向医护的可读摘要，它依赖前面几个 agent 的结构化结果，而不是直接处理所有原始数据。

### 写库

```text
agent_outputs：clinical_summary 输出
agent_events：clinical_summary.completed
patient_state_current.active_problems：可选更新
audit_logs：输入、输出、生成类型、状态
```

### 下游触发

```text
ward_coordinator：如果 summary 中包含 critical focus 或 unresolved issue，可触发
前端 showcase：直接展示最新 summary
```

---

## 6.6 ward_coordinator

### 定位

全局、周期巡检 + 事件触发型 agent。

负责基于全病区患者状态与风险，生成床位优先队列、病区负荷指标和待处理动作。

### 触发条件

```text
1. risk_sentinel 产生 warning/critical；
2. alert open/update/close；
3. admission/discharge/transfer 事件；
4. 固定周期运行，例如每 5-15 分钟；
5. 护士站总览页打开时按需刷新；
6. orchestrator demo-run 全活跃患者模式。
```

### 读取数据

```text
all active admissions
beds
patients
patient_state_current for all active patients
latest risk_assessments
open alerts
latest clinical_summary outputs
orchestrator_runs
```

### 核心处理

```text
1. 计算每张床当前优先级；
2. 合并重复告警，避免告警风暴；
3. 识别新恶化患者；
4. 识别长期未复核患者；
5. 识别 admission/discharge 造成的床位变化；
6. 生成病区级待处理动作。
```

### 输出内容

```text
bed_priority_queue
ward_load_metrics
pending_actions
critical_alerts
new_deterioration_queue
resource_attention_summary
```

项目任务书中明确提出告警管理需要进行 merge、deduplication、priority queue 和跨床位调度，这正是 ward_coordinator 的核心职责。

### 写库

```text
agent_outputs：ward_coordinator 输出
agent_events：ward_coordinator.completed
audit_logs：全局输入摘要、输出、运行状态
```

---

## 7. 推荐调度逻辑

## 7.1 实时事件调度

### vitals 事件

```text
on_vital_event(event):
    write events
    write vital_sign_events
    run bedside_monitor(patient_id)

    run patient_memory(patient_id)

    if bedside.urgency_level in ["warning", "critical"]:
        run risk_sentinel(patient_id)
    else:
        mark risk_sentinel optional

    if risk changed or critical:
        run clinical_summary(patient_id)
        run ward_coordinator()
```

---

### intervention 事件

```text
on_intervention_event(event):
    write events
    write intervention_events
    run intervention_tracker(patient_id, mode="register")

    run patient_memory(patient_id)

    schedule intervention_tracker(patient_id, mode="evaluate", after=observation_window)

    if intervention_tracker.response in ["non_responsive", "deteriorated"]:
        run risk_sentinel(patient_id)
        run clinical_summary(patient_id)
        run ward_coordinator()
```

---

### lab 事件

```text
on_lab_event(event):
    write events
    write lab_events
    run patient_memory(patient_id)

    if lab abnormal_flag in ["high", "low"] or lab_type in ["lactate", "creatinine", "abg"]:
        run risk_sentinel(patient_id)

    if risk changed:
        run clinical_summary(patient_id)
        run ward_coordinator()
```

---

### admission/discharge/transfer 事件

```text
on_admission_state_change(event):
    update admissions
    update beds
    update patient_state_current

    run ward_coordinator()
```

---

## 7.2 周期调度

建议后续加入轻量 scheduler。

```text
每 1-5 分钟：
    检查是否有 pending intervention 到达评估窗口

每 5-15 分钟：
    risk_sentinel 巡检 active patients
    ward_coordinator 更新病区队列

每 6 小时：
    clinical_summary 生成单患者阶段性摘要

每 24 小时：
    clinical_summary 生成查房摘要
    ward_coordinator 生成全病区查房优先级
```

---

## 8. Orchestrator 运行模式

orchestrator 不是 agent，它是流程控制器。

### 8.1 单患者模式

用于前端点击、demo-run、调试。

```text
POST /api/v1/orchestrator/demo-run
patient_id = p1
```

推荐 step 顺序：

```text
1. bedside_monitor
2. intervention_tracker
3. patient_memory
4. risk_sentinel
5. clinical_summary
```

注意：

```text
ward_coordinator 可以作为 optional global step
```

---

### 8.2 全活跃患者模式

用于病区级刷新。

```text
POST /api/v1/orchestrator/demo-run
scope = all_active
```

推荐 step 顺序：

```text
for each active patient:
    bedside_monitor
    intervention_tracker
    patient_memory
    risk_sentinel
    clinical_summary

after all patients:
    ward_coordinator
```

---

### 8.3 事件驱动模式

用于真实运行。

```text
event arrives
→ route by event_type
→ run minimal required agent chain
→ only trigger expensive agents when needed
```

原则：

```text
不要每条 vitals 都跑完整闭环；
不要每次都生成 clinical_summary；
不要每次都刷新 ward_coordinator；
只有风险变化、重要干预结果、出入院变化时才触发重型 agent。
```

---

## 9. 状态更新与写库规范

### 9.1 原始事件表

```text
events：
    存所有外部事件统一入口

vital_sign_events：
    存结构化生命体征

intervention_events：
    存结构化治疗干预

lab_events：
    存结构化实验室检查
```

---

### 9.2 Agent 输出表

```text
agent_outputs：
    存每个 agent 的结构化输出

agent_events：
    存 agent 生命周期事件
    例如 started / completed / failed / degraded / pending

audit_logs：
    存输入、输出、错误、LLM raw response、fallback 信息
```

---

### 9.3 当前状态表

```text
patient_state_current：
    存面向下游和前端的最新状态

patient_state_snapshots：
    存 memory 快照和历史状态
```

---

### 9.4 风险与告警表

```text
risk_assessments：
    存每次风险评估

alerts：
    存当前打开或已处理的告警
```

---

## 10. 时间窗口设计

建议统一使用以下窗口。

```text
bedside_monitor：
    30-90 分钟即时窗口
    6 小时趋势窗口

intervention_tracker：
    根据干预类型选择前后窗口
    fluid: 30-120 分钟
    vasopressor: 15-90 分钟
    ventilator_change: 30-120 分钟
    lab response: 2-6 小时

patient_memory：
    1-6 小时短期
    24 小时中期
    72 小时或入 ICU 以来长期

risk_sentinel：
    最近一次 memory snapshot
    最近 6 小时趋势
    最近 24 小时风险历史

clinical_summary：
    6 小时短摘要
    24 小时查房摘要

ward_coordinator：
    当前 open alerts
    最近 6-24 小时风险变化
```

---

## 11. 风险升级逻辑

推荐使用分级触发。

```text
info：
    仅写入状态，不触发全链路

warning：
    触发 risk_sentinel
    必要时触发 clinical_summary
    ward_coordinator 下次周期更新

critical：
    立即触发 risk_sentinel
    立即创建或更新 alert
    立即触发 clinical_summary
    立即触发 ward_coordinator
```

---

## 12. Intervention pending 机制

这是必须单独设计的部分。

### 12.1 为什么需要 pending

很多干预不能在发生瞬间判断效果。

例如：

```text
500ml fluid 后 MAP 是否改善，需要观察 30-120 分钟
升压药调整后 MAP 变化，需要观察 15-90 分钟
呼吸机参数调整后 SpO2 / PaO2 变化，需要观察 30-120 分钟
```

### 12.2 推荐状态

```text
pending
ready_for_evaluation
completed
insufficient_data
expired
```

### 12.3 推荐流程

```text
intervention event arrives
→ intervention_tracker 写 pending
→ scheduler 检查 observation_window
→ 到时间后重新触发 intervention_tracker
→ 读取 before/after 数据
→ 输出 response
→ patient_memory 更新
→ risk_sentinel 判断是否升级
```

---

## 13. 回放与可观测逻辑

每次 agent 运行都应该形成完整链路：

```text
orchestrator_runs
  └── step result
        ├── agent_name
        ├── patient_id
        ├── input_window
        ├── input_sources
        ├── output_id
        ├── status
        ├── error
        ├── started_at
        └── completed_at
```

每个 agent 同时写：

```text
agent_events.started
agent_outputs
agent_events.completed / degraded / failed
audit_logs
```

这样前端 showcase 可以展示：

```text
1. 原始事件；
2. agent 运行顺序；
3. 每一步输入来源；
4. 每一步输出；
5. 风险如何被升级；
6. ward_coordinator 如何重新排序。
```

---

## 14. 推荐最终流程图

```text
External Client / Timer / Simulator
        |
        v
      events
        |
        v
+------------------+
|   orchestrator   |
+------------------+
        |
        +----------------------+
        |                      |
        v                      v
vital_sign_events        intervention_events
        |                      |
        v                      v
bedside_monitor       intervention_tracker
        |                      |
        +----------+-----------+
                   |
                   v
            patient_memory
                   |
                   v
            risk_sentinel
                   |
          +--------+--------+
          |                 |
          v                 v
   clinical_summary     alerts / risk_assessments
          |                 |
          +--------+--------+
                   |
                   v
            ward_coordinator
                   |
                   v
          frontend dashboard / showcase
```

---

## 15. 最终结论

你们系统的最合理运行逻辑不是“所有 agent 不定时乱跑”，也不是“每次事件都跑完整闭环”，而是：

```text
bedside_monitor 和 intervention_tracker 由原始事件触发；
patient_memory 跟随上游输出更新；
risk_sentinel 由 memory/risk event 触发，并带周期巡检；
clinical_summary 由风险变化、查房时间或按需查看触发；
ward_coordinator 由 critical alert、出入院变化和周期巡检触发；
orchestrator 统一记录每一步，保证可回放、可审计、可展示。
```

这套逻辑最适合你们当前已经完成的 FastAPI + PostgreSQL + agent event bus + frontend showcase 架构，也最适合后续接入 LLM。
