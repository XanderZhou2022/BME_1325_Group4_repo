# 一、推荐的 agent 总体数量与分层

如果做一个**课程项目可落地版本**，我建议总共设计 **8 类 agent**。注意这里的“8 类”是类型，不是实例数量。真正运行时，其中一部分会按床位复制。

## 模块 A：中央协调层

### 1. ICU Orchestrator Agent（1 个）

这是整个 ICU 系统的总调度 agent，相当于病房的数字总控台。

它的核心职责不是做医学判断，而是：

- 接收事件
- 决定该唤醒哪些 agent
- 组织信息流
- 聚合最终输出
- 控制告警级别与消息路由

它对应的是医疗多智能体系统里常见的 coordinator / director 角色，也就是由一个中央 agent 分解任务、调用下游 agent，再汇总结果的层级式结构。

------

## 模块 B：床位级感知与分析层

这一层每张床都要有自己的状态处理单元。

### 2. Bedside Monitor Agent（5 个，每床 1 个）

这是最底层的实时状态感知 agent。

它负责读取每张床的：

- 心率 HR
- 血压 BP / MAP
- 呼吸频率 RR
- 血氧 SpO₂
- 体温 Temp
- 尿量
- 呼吸机参数
- 输液/升压药/镇静药状态

它不直接下结论，而是做两件事：

第一，把原始数值转换成**结构化状态摘要**。
 例如不是只说 “MAP=61”，而是说：
 “过去 90 分钟平均 MAP 持续下降，当前低于目标阈值，且对最近一次补液反应有限。”

第二，负责做最基础的本地异常触发。
 例如：

- 持续低氧
- 低血压
- 心动过速
- 尿量下降
- 呼吸机峰压异常

这类 agent 对应 survey 里 time-series signals 方向中那种把自然语言目标或系统输入转换为结构化分析任务的 computational analyst / signal orchestrator。

------

### 3. Intervention Tracker Agent（5 个，每床 1 个）

这个 agent 专门看“做了什么治疗，以及做完以后有没有变化”。

它主要追踪：

- 补液前后血压变化
- 升压药调整后的 MAP 反应
- 呼吸机参数调整后的氧合变化
- 退热/抗感染后体温与炎症指标变化
- 镇静调整后的 RASS / 谵妄表现变化

这个 agent 很关键，因为 ICU 不是静态判断，而是**干预—反应—再评估**的闭环。它的输出会告诉系统：

- 当前变化更像“自然波动”还是“治疗无效”
- 是否出现“治疗后仍恶化”
- 是否需要升级关注

它本质上是把时序分析从“单点监测”推进到“动作-结果因果链”。

------

### 4. Risk Sentinel Agent（5 个，每床 1 个）

这是每张床的风险预警 agent，也是系统里最接近“临床推理”的一层。

它接收来自：

- Bedside Monitor Agent 的状态摘要
- Intervention Tracker Agent 的干预反应摘要
- 病历/实验室/病程历史
- 必要时的 ICU guideline / rule / scoring tool

它输出的不是最终诊断，而是**风险画像**。比如：

- 感染恶化风险：高
- 休克持续风险：中高
- 呼吸衰竭进展风险：高
- AKI 风险：中
- 镇静过深/谵妄风险：中

我建议它的输出统一成结构化格式，例如：

- risk_type
- confidence
- evidence
- time_window
- escalation_level
- recommended_next_attention

这样后面所有 agent 都好接。

这个角色对应 survey 里 doctors-supporting diagnosis & decision support 的 diagnostic assistant 思路，但在你们项目里要更保守：它只做风险识别和提醒，不做最终治疗决定。医疗 agent 的综述也强调这类系统应保留 mandatory verification / human-in-the-loop。

------

### 5. Patient Memory Agent（5 个，每床 1 个）

这是每张床的“病程记忆体”。

它维护三层记忆：

- **短期记忆**：最近 1–6 小时的重要变化
- **中期记忆**：最近 24 小时的关键事件
- **长期记忆**：入 ICU 以来的病程摘要、既往史、关键转折点

它和普通数据库不同。数据库是存数据，这个 agent 是存**可供其他 agent 调用的病程语义摘要**。
 例如它会维护：

- 当前主要问题是什么
- 最近一次明显恶化发生在什么时候
- 哪些干预有效，哪些无效
- 当前最需要注意的 unresolved issue 是什么

这正对应 healthcare agent 里反复强调的 episodic memory、semantic memory 和 central memory hub：不仅保持连续性，还为多个 specialist agent 提供共享上下文。

------

## 模块 C：共享专家层

这些 agent 不按床位复制，而是全 ICU 共用。谁需要谁调用。

### 6. Clinical Summary Agent（1–2 个）

这个 agent 的任务是把复杂 ICU 数据整理成面向医护的“可读摘要”。

它负责生成三种文档：

- 单床位 24h 查房摘要
- 单床位当前 problem list
- ICU 全病房优先级摘要

它依赖的不是原始数据，而是来自前面几个 agent 的结构化结果。
 它要把它们整合成临床语言，例如：

“Bed 07：过去 6 小时血流动力学持续不稳。补液后 MAP 改善有限，去甲肾上腺素需求增加。乳酸较 4 小时前上升。当前最需要排查感染灶控制不足与持续性休克。”

这个 agent 很适合做给医生、护士演示的核心可视化成果。

------

### 7. Ward Coordinator Agent（1 个）

这是病房级 agent，不是看单个患者，而是看 20 张床整体。

它主要负责：

- 比较 20 张床的风险优先级
- 处理“告警风暴”
- 生成护士站/值班医生的关注列表
- 做资源层面的排序，比如“谁最该先查房”“谁最该先复核”

它接收所有床位的 Risk Sentinel 输出后，形成：

- top-K highest-risk beds
- new deterioration queue
- unresolved critical alerts
- family communication pending queue

这个 agent 非常重要，因为 ICU 的痛点不是只看一个病人，而是**同时要看很多病人，且注意力有限**。它对应 survey 里 workflow coordinator 和 hospital automation / coordination 的方向。 

------

## 模块 D：人文沟通层

### 8. Compassion & Family Communication Agent（1–2 个）

这是你们项目最有特色的一层。

它不碰临床决策，只做“人文沟通翻译”。

它主要负责三件事：

第一，给家属生成**可理解版每日摘要**。
 例如：
 “今天最主要的问题仍然是血压不稳定和感染控制。团队已经持续给药并密切监测。和昨天相比，氧合稍有改善，但循环支持仍然较多。”

第二，生成 ICU diary 风格的记录。
 这样如果患者后期苏醒，可以回顾这段 ICU 经历。

第三，识别需要优先沟通的床位。
 例如：

- 病情变化大
- 风险明显上升
- 24 小时内家属未收到清晰更新
- 处于重大转折点

这个 agent 依赖 Patient Memory Agent 和 Clinical Summary Agent 的结果，但必须经过一个“去术语化 / 降复杂度”的转换层。医疗 agent 的 survey 也专门强调 persona、memory 和 communication 在高同理心场景中的重要性。 

------

# 二、推荐的 agent 数量配置

如果按 20 床位 ICU 来算，推荐配置是：

- ICU Orchestrator Agent：1
- Bedside Monitor Agent：5
- Intervention Tracker Agent：5
- Risk Sentinel Agent：5
- Patient Memory Agent：5
- Clinical Summary Agent：1
- Ward Coordinator Agent：1
- Compassion & Family Communication Agent：1






# 三、具体的 agent 之间如何交互

这里最关键的不是“谁和谁聊天”，而是**谁给谁传什么结构化信息**。

我建议所有 agent 的信息交换都走统一格式，至少包含：

- patient_id / bed_id
- timestamp
- event_type
- source_agent
- summary
- evidence
- urgency
- next_action_hint

这样后面系统非常容易扩展。

------

## 流程 1：生命体征异常触发链

这是 ICU 最基础的一条链。

### Step 1：事件产生

某床位出现新的监测事件，例如：

- Bed 12 的 MAP 连续 20 分钟 < 65
- SpO₂ 从 95% 降到 88%
- 尿量 4 小时持续偏低

### Step 2：ICU Orchestrator 唤醒 Bedside Monitor Agent

Orchestrator 把这条事件路由给对应床位的 Bedside Monitor Agent。

### Step 3：Bedside Monitor Agent 输出状态摘要

它把原始监测值压缩成一个临床摘要，例如：

- 当前异常是什么
- 持续多久
- 是瞬时波动还是趋势恶化
- 与此前 1 小时相比变化如何

然后传给：

- Patient Memory Agent
- Risk Sentinel Agent

### Step 4：Patient Memory Agent 更新病程上下文

它记录：

- 这次异常开始时间
- 是否为重复事件
- 最近是否出现相同模式
- 过去是否对类似情况有响应历史

### Step 5：Risk Sentinel Agent 结合上下文做风险解释

它会整合：

- 当前状态摘要
- 历史病程
- 近期干预反应
- 实验室结果

然后输出：

- 风险类型
- 风险等级
- 主要证据
- 是否需要升级提醒

### Step 6：Ward Coordinator Agent 接收风险结果

如果只是低级提醒，保留在本床位视图。
 如果达到高级别，推送到病房级优先队列。

### Step 7：Clinical Summary Agent 更新单床位问题摘要

它会把这个新风险写进当前床位的最新 problem list。

------

## 流程 2：治疗干预后的闭环链

这是 ICU 系统与一般监控系统最大的差别。

### Step 1：系统收到新的治疗事件

例如：

- Bed 05 刚刚补液 500ml
- Bed 08 去甲肾上腺素从 0.08 调到 0.12
- Bed 14 呼吸机 PEEP 调高

### Step 2：Orchestrator 唤醒 Intervention Tracker Agent

它记录这次干预：

- 干预类型
- 时间点
- 剂量/参数变化
- 预期观察窗口

### Step 3：Intervention Tracker Agent 在之后持续收集反馈

它监测：

- 血压是否回升
- 氧合是否改善
- 心率是否下降
- 乳酸是否改善

### Step 4：Intervention Tracker 输出“反应评估”

例如：

- responsive
- partially responsive
- non-responsive
- deteriorating despite intervention

### Step 5：结果传给 Risk Sentinel Agent

Risk Sentinel 不只是知道“现在很危险”，还知道“已经干预过但没好转”。
 这是 ICU 场景里真正有意义的风险升级信号。

### Step 6：结果同步写入 Patient Memory Agent

病程记忆会记录：

- 什么干预有效
- 什么干预无效
- 当前对哪些措施已经耐受差/反应差

### Step 7：Ward Coordinator 决定是否前置该床位

如果某床位“干预后仍恶化”，它在队列中的优先级应该迅速上升。

------

## 流程 3：查房摘要生成链

这是最适合你们演示的一个流程。

### Step 1：到达查房时间事件

例如每天早上 8:00，系统触发 round_event。

### Step 2：Orchestrator 对每张床调用：

- Patient Memory Agent
- Risk Sentinel Agent
- Intervention Tracker Agent

### Step 3：这些 agent 各自输出固定字段

例如：

Patient Memory 输出：

- admission reason
- major ICU course
- unresolved problems

Risk Sentinel 输出：

- current active risks
- top evidence
- escalation flags

Intervention Tracker 输出：

- key interventions in last 24h
- responses to interventions

### Step 4：Clinical Summary Agent 汇总

它生成：

- 当前最重要的 3 个问题
- 过去 24h 的关键变化
- 今天需要优先关注什么

### Step 5：Ward Coordinator 再做病房级排序

把所有床位按优先级排序后给值班医生一个总览。

------

## 流程 4：家属沟通与人文关怀链

这是你们项目里很有特色的一条链。

### Step 1：Compassion Agent 定期读取

- Patient Memory Agent 的病程摘要
- Clinical Summary Agent 的医护摘要
- Ward Coordinator 的“待沟通队列”

### Step 2：Compassion Agent 判断是否需要触发沟通

例如：

- 病情明显变化
- 今天进行了重大干预
- 已超过一定时间未形成家属版更新
- 患者仍深度镇静/无法交流

### Step 3：Compassion Agent 生成双版本内容

一个版本给医护预览，语言更专业。
 一个版本给家属，语言更柔和、更通俗。

### Step 4：结果回写 Patient Memory Agent

因为“已完成一次家属沟通”本身也是病程上下文的一部分。

------

# 四、哪些 agent 之间必须直接传信息

如果你想把“信息流关系”说得非常清楚，可以直接记下面这组核心边：

## 1. ICU Orchestrator → Bedside Monitor Agent

传递：监测事件、实验室事件、设备事件、查房事件

## 2. Bedside Monitor Agent → Patient Memory Agent

传递：状态摘要、异常时间窗、趋势标签

## 3. Bedside Monitor Agent → Risk Sentinel Agent

传递：实时异常摘要、趋势变化、原始证据引用

## 4. Intervention Tracker Agent → Risk Sentinel Agent

传递：干预类型、反应评估、是否“治疗后仍恶化”

## 5. Intervention Tracker Agent → Patient Memory Agent

传递：关键干预事件、有效/无效经验

## 6. Patient Memory Agent → Risk Sentinel Agent

传递：病程背景、历史模式、既往关键事件

## 7. Patient Memory Agent → Clinical Summary Agent

传递：病程主线、未解决问题、近 24h 关键转折点

## 8. Risk Sentinel Agent → Ward Coordinator Agent

传递：风险等级、优先级、告警类别、证据摘要

## 9. Risk Sentinel Agent → Clinical Summary Agent

传递：当前活跃风险、最主要证据、推荐关注点

## 10. Ward Coordinator Agent → Clinical Summary Agent

传递：病房级排序、优先查房名单、拥塞信息

## 11. Clinical Summary Agent → Compassion Agent

传递：医护版摘要、今日变化、需要翻译给家属的重点

## 12. Patient Memory Agent → Compassion Agent

传递：病人病程背景、此前沟通记录、长期 narrative

------

# 五、我最推荐的系统交互模式：共享状态板，而不是 agent 两两私聊

如果你们真的要实现，我非常建议采用一种更稳定的方式：

不是让 agent A 直接自由地发消息给 agent B，
 而是让所有 agent 都**读写同一个共享患者状态板（shared patient state board）**。

也就是：

- Bedside Monitor 写入：最新生命体征摘要
- Intervention Tracker 写入：最新干预与反应
- Risk Sentinel 写入：当前风险列表
- Patient Memory 写入：病程记忆
- Clinical Summary 读取所有字段后生成总结
- Ward Coordinator 读取所有床位的风险板
- Compassion Agent 读取 summary + memory 生成家属版摘要

这种方式和医疗 multi-agent 研究里提到的 environment-driven coordination 很一致：agent 不一定要彼此不断对话，而是围绕一个持久的、共享的、可查询的环境协作。这样更稳定，也更像真实 ICU 信息系统。