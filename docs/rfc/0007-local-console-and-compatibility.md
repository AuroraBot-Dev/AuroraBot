# RFC 0007：本地控制台与提取模块兼容层

状态：已接受
日期：2026-07-11

## 背景

冻结系统的 localhost 控制台采用“registry → commands → shell”分层，便于本地诊断。部分冻结实现已被提取到 `src/`，其中仍会导入历史 `src.config.Config`。

## 决策

`src/config.py` 是 vNext 唯一公开配置入口。它加载 RFC 0002 TOML 快照，并提供仅含路径、日志级别与非秘密模型标识的 `Config` 兼容门面。新 vNext 代码接收不可变的 `AuroraConfig`；兼容门面不得从环境变量读取结构性配置，也不得成为模型、应用或 Kernel 的隐式全局配置来源。

为使冻结模型网关能完成不发起调用的初始化，兼容门面在 TOML 未声明 `multimodal` 时复用 `quality`，未声明 `embedding` 时使用历史的 `openai/text-embedding-3-small` 标识。这两个回退不是 vNext 模型角色授权，也不得被 Node 使用。

`src/localhost` 提供分层的开发控制台：`registry` 声明命令、`commands` 执行业务用例、`shell` 负责交互。它可以投递 AMP、推进周期、查询记录和查看状态，但不得直接写 Kernel 记录或调用 Platform 私有 client。裸文本等价于 `/say`。

提取的 AI、MCP、App、Sandbox 和工具模块被视为**兼容候选**，不是 vNext 已启用能力。它们只能使用 `Config` 的兼容别名；任何将其接入运行图、MCP 配置、YAML 配置、模型调用或外部效果的行为，必须先完成 RFC 0004 或 RFC 0005。

## 验收标准

1. `uv run python -m src.localhost.cli console` 能经 AMP/Kernel 用例完成 `/say`、`/cycle` 和 `/record`。
2. 提取模块可导入 `src.config.Config`，且不改变 vNext TOML 配置优先级。
3. 根目录旧 `bot.py` 不作为 vNext 入口。

## 迁移影响

旧 localhost 的 `/reload`、`/invoke`、`/tools`、`/apps`、记忆与自我流命令不迁移；它们依赖的旧运行时或未接受的扩展契约保持冻结。
