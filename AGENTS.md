# AuroraBot

AuroraBot 是以因果事件、同构 Agent 和主动节律为核心的自主智能体框架。当前工作树只保存现行实现；设计判断以
已接受 RFC 和当前公共契约为依据。

## Architecture authority

- `docs/rfc/` 是唯一设计基准，RFC 0012 定义当前运行时基线。
- 已接受 RFC 高于 README、注释、配置样例和现有代码。
- 影响模块边界、事件、配置、扩展或模型调用契约的改动，必须先更新或新增 RFC。
- 当前 Agent 闭环以 RFC 0012 为准；RFC 0001 提供稳定的模块与因果边界。

## Project layout

```text
config/         TOML 主配置、领域配置与 profile 覆盖
docs/rfc/       RFC 0000—0012
src/kernel/     Task、Agent、邮箱、Activity、因果与 SQLite 运行态
src/agents/     同构 Agent handler 与内建委派能力
src/ai/         宽泛模型网关
src/localhost/  本地业务服务、scheduler 与开发者调试接口
src/dashboard/  Dashboard 后端路由/API 适配层
src/platform/   平台生态适配、能力目录与 AMP 归一化
src/apps/       内建原生 AMP-MCP 应用
src/sandbox/    独立沙箱组件；当前 Agent 运行时不启用
src/utils/      无上层依赖的通用工具
tests/          契约、集成与回归测试
```

## Hard boundaries

- Kernel 只负责事件、Task/Agent 状态、邮箱、Activity 调度和因果边界；不决定认知内容，也不直接执行平台效果。
- Agent handler 只能读取 `AgentContext` 并返回 `AgentDecision`；不得直接写运行态、调用 Provider 或平台 Client，
  也不得绕过 Activity 与因果记录。
- Platform 将外部生态归一化为 AMP 输入，并执行 `effect.requested`；执行结果必须以新事件回到 Kernel。
- `localhost` 提供业务用例；`dashboard` 只提供路由/API 适配，不能绕过 `localhost` 直接操作 Kernel。
- `utils` 不得依赖 `kernel`、`ai`、`platform`、`nodes`、`localhost` 或 `dashboard`。

## Workspace and configuration

- Kernel 工作区固定为 `data/kernel/inbox/`、`process/`、`archive/`。
- 外部 AMP 与终态 Task 归档使用 JSON，生产者必须先写临时文件再原子改名；运行态使用 SQLite WAL。
- 所有结构性配置使用 TOML；JSON 不得承担主配置职责。
- 密钥仅来自环境变量；`.env` 只用于本地开发，不能定义结构或覆盖任意 TOML 值。

## Runtime and quality

- `uv run python bot.py` 启动单一常驻 `AuroraRuntime`；`uv run aurora` 提供本地调试组合入口。
- Python 3.12，包管理使用 `uv`。
- Ruff 行宽 120，LF，双引号；公开 API 提供类型注解，dataclass 优先 `slots=True`。
- 日志统一使用 `src.utils.log_utils.get_logger()`，级别与字段边界见 `LOGGING.md`。
- 提交前执行 `uv run aurora check`；按改动风险补充定向测试与完整 `uv run pytest`。
