# AI 模拟 ICU 多智能体系统任务书（ICU-Agent Simulation System）

## 一、项目概述

本项目旨在构建一个**面向重症监护病房（ICU）的多智能体模拟系统**，用于复现 ICU 中以生命体征监测、风险评估与协同决策为核心的医疗场景。

与传统“对话式医疗 AI”不同，本系统关注的是一个**高频时序数据驱动、弱语言交互、强风险约束**的环境。在 ICU 中，大多数患者无法进行有效语言交流，其状态主要通过监护设备（如心率、血压、呼吸机参数等）和医疗记录（如检验结果、用药记录）体现。因此，本项目的核心不是构建一个“会聊天的医生”，而是设计一个能够：

- 持续感知患者状态变化
- 基于历史数据进行风险判断
- 协调多角色信息流
- 辅助医生与家属沟通

的**多智能体协同系统（Multi-Agent System）**。

本项目将构建一个包含**20个床位的 ICU 数字病房**，模拟真实 ICU 的运行逻辑，并探索 AI agent 在以下方面的作用：

- 临床风险预警（early warning）
- 信息整合与摘要（clinical summarization）
- 医疗流程辅助（workflow assistance）
- 人文关怀支持（compassion support）

------

## 二、项目目标

本项目的目标分为三个层面：

### （1）系统目标（System-level）

构建一个可运行的 ICU 模拟系统，实现：

- 20床位 ICU 病房模拟
- 患者状态的时间演化（time-series simulation）
- 多 agent 协同运行机制
- 事件驱动的医疗流程（event-driven workflow）

### （2）研究目标（Research-level）

探索以下研究问题：

- 在 ICU 场景中，**多智能体是否优于单一 LLM？**
- 如何设计 agent 才能处理**高频时序医疗数据？**
- 如何在高风险环境下实现**可解释、可控的 AI 辅助？**
- agent 如何在医疗系统中实现**workflow-level augmentation**（而非替代医生）

### （3）应用目标（Application-level）

设计具备潜在落地价值的功能原型：

- ICU 查房摘要系统（round summary）
- 风险预警与提醒系统（alert system）
- 家属沟通辅助系统（family communication assistant）

------

## 三、系统总体架构

系统整体采用**三层架构设计**：

### 1. 患者状态层（Patient State Layer）

每个 ICU 床位对应一个 **Patient Digital Twin**，其状态包括：

- 生命体征：HR、BP、RR、SpO₂、Temp
- 实验室指标：WBC、Lactate、Creatinine、ABG 等
- 治疗信息：用药、输液、机械通气参数
- 病程事件：入院、感染、手术、恶化等

特点：

- 时间序列驱动（time-evolving state）
- 支持历史窗口（6h / 24h / 72h）
- 支持异常检测（threshold + trend）

------

### 2. 多智能体协作层（Agent Layer）

系统核心，由多个功能型 agent 组成：

#### （1）Bedside Monitor Agent

- 输入：实时生命体征
- 输出：状态摘要（trend-aware）
- 作用：从“数据”转为“临床意义”

#### （2）Risk Sentinel Agent

- 功能：风险预测与预警
- 示例：
  - 脓毒症恶化风险
  - 休克风险
  - 呼吸衰竭风险
- 输出：分级提醒（info / warning / critical）

#### （3）Intervention Tracker Agent

- 跟踪治疗措施及效果
- 示例：
  - 输液后血压是否改善
  - 上机后氧合是否改善

#### （4）Rounds Summary Agent

- 生成 ICU 查房摘要：
  - “过去24小时关键变化”
  - “当前最重要问题”
  - “建议关注点”

#### （5）Ward Coordinator Agent

- 全局视角（20床位）
- 功能：
  - 告警排序
  - 优先级管理
  - 医护负载评估

#### （6）Compassion Agent（核心创新点）

- 面向“人文关怀”
- 功能：
  - 家属版每日摘要（非专业语言）
  - ICU Diary（帮助患者恢复记忆）
  - 沟通提醒（如“该床位家属已长时间未更新”）

------

### 3. 人类在环层（Human-in-the-loop Layer）

所有 agent 输出必须经过分级控制：

- 信息级（Info）：仅展示
- 建议级（Suggestion）：提示关注
- 强提醒级（Critical）：需人工确认

**绝不直接执行医疗决策**

------

## 四、核心机制设计

### 1. 事件驱动系统（Event-driven System）

系统由事件触发，而非对话驱动：

典型事件包括：

- 新的生命体征数据
- 实验室结果更新
- 用药变化
- 病情恶化
- 查房时间
- 家属请求沟通

事件触发 agent 运行 → 更新状态 → 输出结果

------

### 2. 状态记忆机制（Temporal Memory）

每个 patient 维护：

- 短期窗口（6h）：即时变化
- 中期窗口（24h）：趋势分析
- 长期窗口（72h+）：病程理解

避免 agent 只看“当前数值”

------

### 3. 告警管理（Alert Orchestration）

目标：避免 ICU “告警风暴”

方法：

- 告警聚合（merge）
- 去重（deduplication）
- 优先级排序（priority queue）
- 跨床位调度（global attention）

------

### 4. 可解释性（Explainability）

每个 agent 输出必须包含：

- 依据数据（evidence）
- 时间窗口（time context）
- 判断逻辑（reasoning trace）

------

## 五、数据设计

### 1. 数据来源（可选）

可参考公开 ICU 数据：

- MIMIC-IV（EHR）
- MIMIC Waveform（监护数据）
- eICU（多中心数据）
- HiRID（高频 ICU 数据）

### 2. 简化方案（课程项目推荐）

构建**模拟数据生成器**：

- 正常 → 恶化 → 干预 → 恢复
- 支持不同病种模板：
  - 感染性休克
  - 呼吸衰竭
  - 术后监护
  - 神经 ICU

------

## 六、前后端设计

### 后端（核心）

模块：

1. Patient State Engine
2. Event Engine
3. Agent Orchestrator
4. Memory Store
5. Alert System
6. Audit Log（记录决策过程）

技术建议：

- FastAPI + Python
- Agent框架：LangChain / 自定义

------

### 前端（展示层）

功能：

- ICU 总览（20床位 dashboard）
- 单床位详情（trend + summary）
- 告警面板
- 查房视图
- 家属沟通界面

技术建议：

- React + PixiJS / Phaser（或 Godot）