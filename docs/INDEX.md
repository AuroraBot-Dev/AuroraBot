# 文档索引

核对日期：2026-11-09。首次使用从[安装配置助手](../examples/START.md)开始；当前文档描述已经实现的行为，历史讨论不作为待办或功能承诺。

## 当前文档

| 文档 | 用途 |
| --- | --- |
| [首次启动](../examples/START.md) | 安装依赖、配置模型、使用唯一的 terminal MCP ReAct 助手 |
| [配置与 MCP](configuration.md) | 数据目录、TOML、模型、外部工具及世界来源 |
| [操作指南](operations.md) | 正式 Bot、TUI、Panel、访问认证、编辑与故障定位 |
| [上下文与运行](context.md) | 模型输入、历史、字符预算、cadence、笔记与自身控制 |
| [当前架构](aurorabot-design-v0.2.3.md) | 包职责、生命周期、执行与传输边界 |
| [公共 ID 目录](aurorabot-id-catalog-v0.2.3.md) | 当前插件实际登记的 ID、类型和提供者 |
| [执行包边界](aurora_agent_extraction_assessment.md) | control / agent / bot 独立性与尚未实现的 harness |
| [开发与验证](development.md) | 检查入口、回归夹具、分发验收和文档维护 |
| [变更与验收记录](CHAGELOG.md) | 按日期保留已发生的变更与验证结果 |

架构、ID 目录与拆包评估保留原文件名以维持现有引用，其正文已按当前代码更新。历史快照保留原内容语境，不回写为“当前已实现”。

## 历史资料

统一存放于 `archive/2026-11-09/`。其中的旧启动命令、版本、状态与计划不代表当前用法；源码位置链接已随回归夹具迁移修正。

| 归档 | 当前应参考 |
| --- | --- |
| [旧启动大全](archive/2026-11-09/START.md) | 首次启动、配置、操作、上下文与开发指南 |
| [初期架构 v0.2.3](archive/2026-11-09/aurorabot-design-v0.2.3.md) | 当前架构 |
| [旧公共 ID 设计](archive/2026-11-09/aurorabot-id-catalog-v0.2.3.md) | 当前实际登记目录 |
| [拆包评估原稿](archive/2026-11-09/aurora_agent_extraction_assessment.md) | 执行包边界 |
| [ReAct 设计讨论](archive/2026-11-09/aurora_bot_react_design.md) | 当前架构、上下文与运行 |
| [主动上下文设计](archive/2026-11-09/aurora_bot_ctx_prompt_design.md) | 上下文与运行 |
| [MCP 通用接入草案](archive/2026-11-09/mcp_unified_access_design.md) | 配置与 MCP |
| [其他客户端 MCP 配置样本](archive/2026-11-09/opencode_like_mcp_config.md) | Aurora 的 schema_version=2 配置 |
| [M2 交接](archive/2026-11-09/m2-handoff.md) | 当前架构、变更记录 |
| [旧里程碑计划](archive/2026-11-09/plan.md) | 当前文档与代码；未完成项须重新确认需求 |
| [11 月 3 日审查](archive/2026-11-09/review-report_2026-11-03.md) | 对应日期的历史审查证据 |
| [TUI 优化候选清单](archive/2026-11-09/tui_optimization_todo.md) | 历史候选项，未作为本次实现范围或新承诺 |

## 维护规则

新增功能同步修改所属主题文档，变更与验收写入 CHAGELOG.md。START.md 只保留初次启动路径。配置、插件和 ID 以代码及验证结果为准，规划必须明确标注未实现。移动文档时同时修正相对链接；旧文档的历史命令不改造成新的操作教程。
