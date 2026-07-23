# AuroraBot RFC

RFC 保存 AuroraBot 已经作出的设计决定。它们不是认识项目的第一站：如果你只是想知道 AuroraBot 是什么、能做什么或
如何运行，请先阅读根目录 [README](../../README.md)。当你准备修改公共行为，或想理解某项约束为何存在时，再来到这里。

## 模块实施规范

每个文件是该模块的完整实施契约，按依赖方向组织：

1. [0100 架构基准、配置与进程入口](0100-architecture.md) — 模块边界、依赖方向、工作区、配置系统、CLI 入口
2. [0101 数据契约](0101-contracts.md) — AMP 信封、AgentContext、AgentDecision、Model/Tool 契约、Capability 协议
3. [0102 Kernel 运行时](0102-kernel.md) — Task/Agent/Mailbox/Activity 生命周期、因果事件、SQLite 持久化、BrainContext
4. [0103 Agent Handler 与能力](0103-agents.md) — AgentHandler 协议、ToolAgent/MemoryAgent、Capability 注册与 dispatch
5. [0104 AI 模型网关](0104-ai-gateway.md) — 模型角色、Provider 路由、双通道、能力协商、异步调度
6. [0105 提示词装配](0105-prompt.md) — PromptCatalog、分层 DTO、PromptComposer、Tool 描述归属
7. [0106 Localhost 运行组合](0106-localhost.md) — 统一输入路由、命令系统、工具分发、自主额度、调试 API
8. [0107 Platform 适配层](0107-platform.md) — Console/Dashboard/MCP adapter、Tool 注册、ToolOutcome、心跳
9. [0108 三层记忆](0108-memory.md) — MemoryService、mem0/ChromaDB、自动注入、MemoryAgent

## 什么时候需要 RFC

影响模块边界、事件、结构配置、扩展协议、模型调用契约、持久化语义或进程组合的改动，需要先更新或新增 RFC。小型
缺陷修复、测试补充、文案改进和不改变公共语义的重构通常不需要 RFC。

## 规范优先级

已接受 RFC 高于 README、注释、配置样例、Issue 模板与现有实现。如果实现与 RFC 冲突，应修正实现；如果原决定需要
改变，应通过新的 RFC 明确取代，而不是让代码和文档各自形成一套事实。

状态含义：

- **草案**：正在讨论，不得作为稳定契约实现。
- **提议**：决策已经完整，等待接受。
- **已接受**：当前规范性基准。
- **已取代**：由后续 RFC 明确替代，仅保留演进记录。
- **已废弃**：仅保留历史，不再适用。
