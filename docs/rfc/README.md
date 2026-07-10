# AuroraBot vNext RFC

本目录是 vNext 的唯一设计基准。RFC 记录可验证的架构决策，不是愿景随笔或旧代码说明。

## 规范优先级

已接受 RFC 高于 README、注释、配置样例、Issue 模板与实现。若实现与 RFC 冲突，应修正实现；若决策需要改变，应以新的 RFC 取代旧 RFC。

## 状态

- **草案**：正在讨论，不得被实现当作稳定契约。
- **提议**：已具备完整决策，等待接受。
- **已接受**：vNext 的规范性基准。
- **已取代**：由后续 RFC 明确取代。
- **已废弃**：保留历史，不再适用。

## 索引

| RFC | 状态 | 主题 |
| --- | --- | --- |
| [0000](0000-rfc-process.md) | 已接受 | RFC 过程与规范语言 |
| [0001](0001-architecture.md) | 已接受 | 架构边界与最小因果闭环 |
| [0002](0002-configuration.md) | 已接受 | TOML 主配置与 JSON 数据边界 |
| [0003](0003-event-contract.md) | 已接受 | AMP、Kernel record、周期与效果回执 |
| [0004](0004-plugin-contract.md) | 草案 | 节点、平台适配器与应用扩展 |
| [0005](0005-model-gateway.md) | 已接受 | 模型角色、能力协商与原生响应 |
| [0006](0006-local-debug-api.md) | 已接受 | 本地运行器与开发调试 HTTP API |
| [0007](0007-local-console-and-compatibility.md) | 已接受 | 本地控制台与提取模块兼容层 |
