# RFC 0012：同构多 Agent 持久化运行时

状态：已接受
日期：2026-07-19

## 背景

RFC 0008 使用 Episode、静态认知图和全局 cycle 表达异步模型、工具续跑与主动节律。随着等待状态、预算、
恢复和效果策略增加，图路由已经演变为隐藏在 `Kernel` 中的工作流状态机，并形成对 AI、Platform 和 localhost
配置的反向依赖。

AuroraBot 需要让多个认知主体独立推进、并行等待外部活动，并以明确的父子关系协作。因此运行时改用同构
Agent、持久化邮箱和监督树，而不再把认知节点编排成全局静态图。

## 决策

### Task、Agent 与监督树

每个外部根 AMP 或 `system.tick` 创建一个 Task 和根 Gate Agent。所有 Agent 使用同一生命周期与消息协议，
由 TOML profile 决定模型角色、提示词、能力和可创建的子 profile。

Agent 可以有界递归创建子 Agent。子 Agent 完成或失败后以新消息回报直接父级；每一条回报都可以恢复父级，
父级可以继续工作或等待其余子级。只有根 Agent 可以请求 `terminal` 效果；子 Agent 可以请求获授权的 `resume`
效果。根 Task 结束时取消整棵监督树。

Task 统一拥有模型调用、工具调用、持续时间和自主日额度。所有后代共享并原子扣减根 Task 预算，不因创建子
Agent 获得额外额度。

### 消息与 Activity

Agent 一次只消费一条持久化邮箱消息，并返回纯 `AgentDecision`。Decision 可以请求模型、请求效果、创建子级、
等待、完成或失败；Agent 不直接写工作区、数据库或调用外部 Client。

模型和效果都是 Activity。Activity 在 Agent turn 事务提交后由异步 worker 执行，结果以新邮箱消息恢复原 Agent。
每个 Agent 同时最多执行一个 turn，不同 Agent 可以并行。模型与原生异步 I/O 使用 asyncio；同步阻塞调用进入
有界线程池。

### 全局脑活动上下文

Runtime 向每个 Agent turn 提供只读 `BrainContextSnapshot`：

- SOUL 基底人格及哈希；
- 所有活跃 Task 和 Agent 的确定性简讯；
- 尚未归属 Agent 的情景事件。

该投影由 Runtime 根据事实和生命周期维护，Agent 不得直接修改。情景可以通过受控 claim 认领，或在默认
30 分钟 TTL 后退出活动投影；原始因果事实不删除。当前部署被视为同一可信人格域，活动内容摘要不按 session
隔离，但不得包含密钥、Provider 私有对象、隐藏推理或未规范化附件。

### 持久化与外部边界

AMP 继续是 Platform、原生 App 与 Kernel 的 UTF-8 JSON 边界，入口仍使用临时文件加原子改名。Kernel 运行态
改为 `process/runtime.sqlite3`，使用 WAL 和事务保存 Task、Agent、邮箱、Activity、因果事实和情景。

一次 Agent turn 必须原子确认 revision、完成输入消息、更新状态并写入所有新消息和 Activity。领取使用租约；
崩溃前未提交的消息可以重新领取。已开始的模型或效果 Activity 重启后失败为 `interrupted_by_restart`，默认不
自动重放。终态 Task 导出规范 JSON 到 `archive/tasks/`。

### 配置与调试接口

`config/agents.toml` 取代 `nodes.toml`。删除 node input/output、edge、`@continuation` 和 advancing edge。
全局 cycle 被事件唤醒调度取代，localhost 仅提供确定性的 `pump(max_turns)` 调试入口。

调试 API 为：

- `GET /v1/debug/status`
- `GET /v1/debug/tasks/{task_id}`
- `GET /v1/debug/agents/{agent_id}`
- `GET /v1/debug/brain-context`
- `POST /v1/debug/pump`

Episode 和 cycle 调试 API 不再存在。

### 包边界与 Platform 布局

运行时代码遵循单向依赖：`utils/contracts ← kernel/ai/platform/agents ← localhost ← dashboard`。配置 DTO 与
模型、AMP、Agent 等稳定契约位于无上层依赖的 `src/contracts`；配置只在组合根显式加载，模块导入不得读取
项目配置或创建运行目录。

Platform 内每个完整适配器使用独立子包。Console、Dashboard 与 MCP 的公共入口分别为
`src.platform.console`、`src.platform.dashboard` 和 `src.platform.mcp`；子包拥有自己的效果执行与外部协议代码，
共享层只保留无平台语义的轻量结果类型，不用继承体系合并不同平台生命周期。

主源码文件以 500 行为可审查性上限；超过时按持久化、入口、查询、执行或协议职责拆分，并由自动测试阻止
无边界的大文件重新出现。该上限不要求把紧密状态机机械切碎，拆分后的模块仍须拥有清晰名称和单一变更原因。

### Memory Agent 边界

本 RFC 只定义 `MemoryQuery`、`MemoryResult`、`MemoryProposal` 与 `MemoryFailure`。未配置 Memory Agent 时返回非
致命 `memory.unavailable`。检索、写入、遗忘、隐私和长期记忆后端由后续 RFC 决定。

## 与既有 RFC 的关系

本 RFC 取代 RFC 0008 的 Episode、认知图、continuation edge、全局 cycle、单模型并发和 JSON snapshot 条款；
取代 RFC 0001、0003、0004 中以 Node/Graph/Episode 表述的认知扩展与调度条款。AMP、因果边界、Platform 唯一
效果执行权、模型网关审计和 localhost 单运行时所有权继续有效。

## 非目标

- 长期记忆实现、跨进程 Agent 集群和远程消息总线。
- 共享隐藏推理或 Provider 托管 Conversation 对象。
- 兼容旧 Episode/Graph 工作区或长期双运行时。

## 验收标准

1. 根 Agent 可直接完成，也可递归创建并行子 Agent；每个子级结果分别恢复父级。
2. 同一 Agent 串行、不同 Agent 并行，且共享预算、深度、子级数和总 Agent 数均受事务约束。
3. 子 Agent 不能请求 terminal 效果；根 Task 结束会取消全部后代和未完成 Activity。
4. 模型与效果结果准确返回请求 Agent，重启和重放不会产生重复终态效果。
5. Brain Context 自动反映人格、全局活动和未归属情景，claim 与 TTL 可审计。
6. Kernel 不依赖 AI、Platform 或 localhost 配置实现。
7. 安装后的 wheel 可从空工作目录导入并启动 CLI；自动边界测试拒绝反向依赖和包级循环。
