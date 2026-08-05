# AuroraBot

AuroraBot 是以因果事件、同构 Agent 和主动节律为核心的自主智能体框架。当前工作树只保存现行实现；设计判断以
已接受 RFC 和当前公共契约为依据。

## Architecture authority

- `docs/rfc/` 是唯一设计基准，RFC 0200 定义 Agent 中心运行时、包边界与进程组合。
- 已接受 RFC 高于 README、注释、配置样例和现有代码。
- 影响模块边界、事件、配置、扩展或模型调用契约的改动，必须先更新或新增 RFC。
- `ARCHITECTURE.md` 是 RFC 0200 的详细实施规划；冲突时以已接受 RFC 为准。

## Project layout

```text
config/         TOML 核心配置、平台偏好、领域配置与 profile 覆盖
aurora/         唯一进程 CLI、平台选择与生命周期组合
docs/rfc/       已接受 RFC 与阅读索引
src/contracts/  无上层依赖的配置、AMP、Agent、模型与记忆契约
src/prompt/     提示词目录、分层 DTO 与模型上下文呈现
src/engine/     完整 Agent 热路径、状态、Activity、因果与 SQLite 运行态
src/agents/     同构 Agent handler 与内建委派能力
src/ai/         宽泛模型网关
src/memory/     自动记忆服务与持久化适配
src/config/     TOML 加载、校验与配置快照
src/localhost/  输入、命令路由、运行时监察与开发者调试接口
src/console/    本地交互 Shell 与输出渲染（热路径外的只读渲染器）
src/platform/   Dashboard、MCP 的协议、持久化、能力与效果适配
src/apps/       内建原生 AMP-MCP 应用
src/sandbox/    独立沙箱组件；当前 Agent 运行时不启用
src/utils/      无上层依赖的通用工具
tests/          契约、集成与回归测试
```

## Hard boundaries

- engine 完整拥有事件、Task/Agent 状态、邮箱、Activity、模型/工具调度和因果热路径；具体实现通过 contracts Port 注入。
- Agent handler 只能读取 `AgentContext` 并返回 `AgentDecision`；不得直接写运行态、调用 Provider 或平台 Client，
  也不得绕过 Activity 与因果记录。
- Platform 将外部生态归一化为 AMP 输入并执行环境效果；只依赖 contracts + utils，不得导入 localhost 或 engine。
- localhost 位于热路径之外，只提供输入、命令、查询与调试 sidecar；engine 不依赖 localhost。
- 依赖方向固定为 `utils/contracts ← prompt/config/engine/ai/memory/platform ← agents/localhost ← aurora`；
  `src` 不得反向导入进程组合层。

## Workspace and configuration

- engine 工作区固定为 `data/engine/inbox/`、`process/`、`archive/`。
- 外部 AMP 与终态 Task 归档使用 JSON，生产者必须先写临时文件再原子改名；运行态使用 SQLite WAL。
- 所有结构性配置使用 TOML；JSON 不得承担主配置职责。
- 配置按包拆分为 `runtime.toml`、`engine.toml`、`models.toml`、`platforms.toml`、`agents.toml`、`apps.toml`、
  `prompts.toml`、`logging.toml` 与 `storage.toml`；profile 只覆盖 runtime。
- 密钥仅来自环境变量；`.env` 只用于本地开发，不能定义结构或覆盖任意 TOML 值。

## Runtime and quality

- `uv run aurora` 使用 preference 默认组合；`--platform`（可重复）构成精确平台集合，`--headless` 不启动外部平台。
- Python 3.12，包管理使用 `uv`。
- Ruff 行宽 120，LF，双引号；公开 API 提供类型注解，dataclass 优先 `slots=True`。
- 主源码文件原则上不超过 500 行；超过 500 行的文件必须考虑架构是否合理或是否应该根据总分结构分包。
- 日志统一使用 `src.utils.logging.get_logger()`，级别与字段边界见 `LOGGING.md`。
- 提交前执行 `uv run aurora check`；按改动风险补充定向测试与完整 `uv run pytest`。
