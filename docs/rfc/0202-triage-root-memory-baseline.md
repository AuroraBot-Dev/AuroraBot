# 0202：Triage、Root 与压缩记忆基线

状态：已接受（TriagePolicy 与 admit 路径已被 RFC 0209 取代）
日期：2026-07-29
来源：取代 RFC 0200 的逐 AMP Task 摄入与 situation claim，取代 RFC 0201 的原始最近对话注入
> 注：RFC 0209 将无工具 TriagePolicy 与特殊 admit 路径替换为同构的入口 triage agent；
> 本 RFC 的防抖批次、三层信息存储、Prompt 形状与留存语义仍然有效。

## 问题

逐条外部事件立即创建 Task，会把平台抖动、连续短消息和无持续语义的通知都放大为一次完整 Agent
循环。随后每个 turn 再注入全局 Task、Agent、situation 和原始历史对话，使第二轮及以后同时承担历史数据、
无关并发状态和重复工具描述。运行时因此难以给延迟、上下文和磁盘增长建立清晰上界。

## 决定

### 单一热路径

外部语义事件采用以下唯一流程：

`AMP -> bounded inbox -> debounce -> triage -> admitted batch -> root Task -> causal journal -> memory projection`

- AMP 摄入只写入持久化 Inbox 和紧凑幂等回执，不直接创建 Task。
- Inbox 以 `session_id` 分区。新事件重置 quiet window，但不得超过首条事件的 max wait，形成动态防抖。
- 到期批次由一个无工具的 Triage 模型判断 `process`、`defer` 或 `discard`。
- `process` 将同一批次一次性创建为一个 Root Task；`defer` 给出明确的下一次可处理时间；`discard`
  删除原始 Inbox 数据。模型或结构化输出失败时默认 `process`，不静默丢失用户输入。
- 已知的供应商瞬时噪声仍在 Platform/App 边界用确定性规则过滤，不占用 Triage 模型。
- 数据库租约仍可称为 claim；面向模型的认知动作统一称为 triage/admit，不再提供
  `aurora.situation.claim`。

### Root 与子代理

- Root 是 admitted batch 的唯一入口。它可以独立完成工作，或通过显式 delegation 创建同构子代理。
- Agent handler 仍是纯函数 `AgentContext -> AgentDecision`，但上下文不再包含全局 Brain 快照或
  ambient situations。
- Root 首轮 user 消息只包含本批次原始事实的有界规范投影和 Triage 摘要；工具/子代理续轮只包含对应结果。
- Tool schema 只通过模型原生 `tools` 字段传递。子代理只接收 assignment、相关记忆与自己的结果，不继承
  Root 的完整事件历史。

### 三层信息存储

- **因果日志**记录收到、Triage 决策、Task/Agent/Activity 和终态结果，是审计与恢复依据。
- **会话工作记忆**只保存每个 `session_id` 的有界滚动摘要。
- **长期事实**只保存可复用、去重、带来源的稳定事实；并非每个决定都进入长期事实。
- Memory 投影在 Task 终态后更新，不阻塞 Root 的用户反馈。Prompt 读取的是一次不可变 Memory snapshot，
  不直接回放因果日志或原始历史对话。

### Prompt 形状

一次新的模型调用最多包含三类消息：

1. stable system：身份、世界规则和 Agent profile；
2. memory system：当前会话摘要与少量相关长期事实，仅在非空时存在；
3. user：本次 admitted event batch、Tool receipt 或 child report。

任何一层都必须有字符上界。运行时不得注入全局 active Task/Agent 列表。

### 留存

- Inbox 原始 payload 只保存到 Triage 完成；`process` 和 `discard` 后立即删除，`defer` 只保留到下一次决策。
- 幂等回执与 Triage 因果事件使用紧凑字段，不复制原始 AMP payload。
- 终态 Task 仍遵循 RFC 0201 的先归档后清理；会话摘要和长期事实独立存放于 Memory SQLite。
- 新基线不提供旧 situation、全局 Brain prompt 或 mem0/Chroma 数据结构的兼容读写。

## 结果

连续短消息只触发一次 Triage 和一次 Root Task；第二轮上下文由当前事件、当前续轮和压缩记忆决定，不随历史
Task 总数线性增长。运行时数据的主要上界由待处理 Inbox、活跃 Task、归档投影和有界 Memory 决定。
