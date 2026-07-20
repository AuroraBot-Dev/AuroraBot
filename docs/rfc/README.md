# AuroraBot RFC

RFC 保存 AuroraBot 已经作出的设计决定。它们不是认识项目的第一站：如果你只是想知道 AuroraBot 是什么、能做什么或
如何运行，请先阅读根目录 [README](../../README.md)。当你准备修改公共行为，或想理解某项约束为何存在时，再来到这里。

## 当前阅读顺序

1. [RFC 0012](0012-homogeneous-agent-runtime.md) 定义当前 Agent 运行时：Task、同构 Agent、邮箱、Activity、监督树与预算。
2. [RFC 0014](0014-parallel-platform-composition-and-preferences.md) 定义当前进程入口、Platform 组合、偏好配置与包位置。
3. [RFC 0001](0001-architecture.md) 提供仍然稳定的因果边界与依赖方向。
4. 其余 RFC 用于追溯具体契约；若内容与后续 RFC 冲突，以编号更高且明确取代它的已接受 RFC 为准。

特别注意：RFC 0009、0010、0011 和 0013 记录了演进过程中的重要决定，但其中的旧 CLI、旧包位置或旧运行时术语可能
已被 RFC 0012/0014 取代。阅读它们时应结合上面的当前基准。

## 什么时候需要 RFC

影响模块边界、事件、结构配置、扩展协议、模型调用契约、持久化语义或进程组合的改动，需要先更新或新增 RFC。小型
缺陷修复、测试补充、文案改进和不改变公共语义的重构通常不需要 RFC。

RFC 应描述可验证的决定，而不是只写愿景。完整格式、状态变化和验收要求见 [RFC 0000](0000-rfc-process.md)。

## 规范优先级

已接受 RFC 高于 README、注释、配置样例、Issue 模板与现有实现。如果实现与 RFC 冲突，应修正实现；如果原决定需要
改变，应通过新的 RFC 明确取代，而不是让代码和文档各自形成一套事实。

状态含义：

- **草案**：正在讨论，不得作为稳定契约实现。
- **提议**：决策已经完整，等待接受。
- **已接受**：当前规范性基准。
- **已取代**：由后续 RFC 明确替代。
- **已废弃**：仅保留历史，不再适用。

## 索引

| RFC | 状态 | 主题 |
| --- | --- | --- |
| [0000](0000-rfc-process.md) | 已接受 | RFC 过程与规范语言 |
| [0001](0001-architecture.md) | 已接受 | 架构边界与因果闭环 |
| [0002](0002-configuration.md) | 已接受 | TOML 主配置与 JSON 数据边界 |
| [0003](0003-event-contract.md) | 已接受 | AMP、Kernel record、周期与效果回执 |
| [0004](0004-plugin-contract.md) | 已接受 | 节点、平台适配器与应用扩展 |
| [0005](0005-model-gateway.md) | 已接受 | 模型角色、能力协商与原生响应 |
| [0006](0006-local-debug-api.md) | 已接受 | 本地运行用例与开发调试 HTTP API |
| [0007](0007-local-console-and-config-facade.md) | 已接受 | 本地控制台与显式配置快照 |
| [0008](0008-first-cognitive-loop.md) | 已取代 | 首轮认知图、Episode 与主动节律；由 RFC 0012 取代 |
| [0009](0009-bot-loop-entry.md) | 已接受 | 常驻 Bot 组合入口；部分入口由 RFC 0014 更新 |
| [0010](0010-dashboard-chat.md) | 已接受 | Dashboard 聊天适配与本地聊天室；包位置由 RFC 0014 更新 |
| [0011](0011-current-project-baseline.md) | 已接受 | 项目基线与源码归档边界；运行时由 RFC 0012 更新 |
| [0012](0012-homogeneous-agent-runtime.md) | 已接受 | 当前同构多 Agent 持久化运行时 |
| [0013](0013-unified-command-routing-and-entry.md) | 已接受 | 统一命令路由；进程入口由 RFC 0014 更新 |
| [0014](0014-parallel-platform-composition-and-preferences.md) | 已接受 | 当前并行平台组合与偏好配置 |
| [0015](0015-agent-publication-and-communication-boundary.md) | 已接受 | Agent 发布、通信授权与 Task 完成解耦 |
| [0016](0016-mcp-communication-app-contract.md) | 已接受 | MCP 通信 App、消息入口与跨平台投递契约 |
