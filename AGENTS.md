# AuroraBot

AuroraBot 是以因果事件、同构 Agent 和主动节律为核心的自主智能体框架。当前工作树只保存现行实现；设计判断以
已接受 RFC 和当前公共契约为依据。

## Architecture authority

- `docs/rfc/` 是唯一设计基准，RFC 0012 定义 Agent 运行时，RFC 0014 定义平台组合、偏好配置与进程入口。
- 已接受 RFC 高于 README、注释、配置样例和现有代码。
- 影响模块边界、事件、配置、扩展或模型调用契约的改动，必须先更新或新增 RFC。
- 当前 Agent 闭环以 RFC 0012 为准；RFC 0001 提供稳定的模块与因果边界。

## Project layout

```text
config/         TOML 核心配置、平台偏好、领域配置与 profile 覆盖
aurora/         唯一进程 CLI、平台选择与生命周期组合
docs/rfc/       RFC 0000—0014
src/contracts/  无上层依赖的配置、AMP、Agent、模型与记忆契约
src/kernel/     Task、Agent、邮箱、Activity、因果与 SQLite 运行态
src/agents/     同构 Agent handler 与内建委派能力
src/ai/         宽泛模型网关
src/localhost/  统一输入、效果调度、scheduler 与开发者调试接口
src/platform/   Console、Dashboard、MCP 的协议、持久化、能力与效果适配
src/apps/       内建原生 AMP-MCP 应用
src/sandbox/    独立沙箱组件；当前 Agent 运行时不启用
src/utils/      无上层依赖的通用工具
tests/          契约、集成与回归测试
```

## Hard boundaries

- Kernel 只负责事件、Task/Agent 状态、邮箱、Activity 调度和因果边界；不决定认知内容，也不直接执行平台效果。
- Agent handler 只能读取 `AgentContext` 并返回 `AgentDecision`；不得直接写运行态、调用 Provider 或平台 Client，
  也不得绕过 Activity 与因果记录。
- Platform 将外部生态归一化为 AMP 输入并执行环境效果；只依赖 localhost 窄端口，不得直接操作 Kernel。
- localhost 统一领取和路由效果、持久化 Platform outcome，并提供 Console、Dashboard 共用的输入与命令用例。
- 依赖方向固定为 `utils/contracts ← kernel/ai/agents ← localhost ← platform ← aurora`；`src` 不得反向导入进程组合层。

## Workspace and configuration

- Kernel 工作区固定为 `data/kernel/inbox/`、`process/`、`archive/`。
- 外部 AMP 与终态 Task 归档使用 JSON，生产者必须先写临时文件再原子改名；运行态使用 SQLite WAL。
- 所有结构性配置使用 TOML；JSON 不得承担主配置职责。
- `config/aurora.toml` 与 `config/preference.toml` 分别形成核心配置和平台偏好快照，不得跨文件任意覆盖。
- 密钥仅来自环境变量；`.env` 只用于本地开发，不能定义结构或覆盖任意 TOML 值。

## Runtime and quality

- `uv run aurora` 使用 preference 默认组合；`--console`、`--dashboard`、`--mcp` 形成精确平台集合，`--headless` 不启动外部平台。
- Python 3.12，包管理使用 `uv`。
- Ruff 行宽 120，LF，双引号；公开 API 提供类型注解，dataclass 优先 `slots=True`。
- 主源码文件原则上不超过 500 行；超过时按明确职责拆分，并由边界测试约束。
- 日志统一使用 `src.utils.log_utils.get_logger()`，级别与字段边界见 `LOGGING.md`。
- 提交前执行 `uv run aurora check`；按改动风险补充定向测试与完整 `uv run pytest`。
