# AuroraBot RFC

RFC 记录 AuroraBot 已接受的设计决定。涉及模块边界、事件、结构配置、扩展协议、模型调用、持久化语义或进程组合的改动，必须先更新或新增 RFC。

## 当前基准

1. [0200 Agent 中心运行时架构](0200-agent-centered-runtime.md) - 包边界、Port 注入、engine 热路径、localhost 监察与组合根
2. [0201 有界上下文与运行态留存](0201-bounded-context-and-runtime-retention.md) - 会话级记忆、上下文预算、瞬时事件过滤与终态数据生命周期
3. [0202 Triage、Root 与压缩记忆基线](0202-triage-root-memory-baseline.md) - 批量防抖摄入、Triage 决策、Root 上下文与三层信息存储

## 规范优先级

已接受 RFC 高于 README、注释、配置样例与现有实现。`ARCHITECTURE.md` 是 RFC 0200 的详细实施规划；两者冲突时以 RFC 为准。

状态包括：草案、提议、已接受、已取代和已废弃。
