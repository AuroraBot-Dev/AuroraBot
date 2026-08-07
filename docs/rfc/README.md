# AuroraBot RFC

RFC 记录 AuroraBot 已接受的设计决定。涉及模块边界、事件、结构配置、扩展协议、模型调用、持久化语义或进程组合的改动，必须先更新或新增 RFC。

## 当前基准

1. [0200 Agent 中心运行时架构](0200-agent-centered-runtime.md) - 包边界、Port 注入、engine 热路径、localhost 监察与组合根
2. [0201 有界上下文与运行态留存](0201-bounded-context-and-runtime-retention.md) - 会话级记忆、上下文预算、瞬时事件过滤与终态数据生命周期
3. [0202 Triage、Root 与压缩记忆基线](0202-triage-root-memory-baseline.md) - 批量防抖摄入、Triage 决策、Root 上下文与三层信息存储
4. [0203 Agent 自由与运行时边界](0203-agent-freedom-boundary.md) - Prompt 人格、模型行动自由、效果安全与资源边界
5. [0204 Console 本地交互前端](0204-console-local-frontend.md) - Console 脱离平台抽象，改为本地渲染器，Bot 文本默认输出
6. [0205 Agent 状态机收敛与决策链路扁平化](0205-agent-state-and-decision-thinning.md) - 删除 Command 层、Agent 等待状态派生化、Schema v8 迁移
7. [0206 运行时组合与配置快照收敛](0206-runtime-composition-and-configuration-hardening.md) - 强类型平台生命周期、单一启动配置快照与 MCP 边界
8. [0207 Multiagent 委派链与同源记忆](0207-multiagent-delegation-and-unified-memory.md) - 注意力初筛、本体意识委派链、全员被动记忆与可委派记忆 agent 的同源记忆

## 规范优先级

已接受 RFC 高于 README、注释、配置样例与现有实现。`ARCHITECTURE.md` 是 RFC 0200 的详细实施规划；两者冲突时以 RFC 为准。

状态包括：草案、提议、已接受、已取代和已废弃。
