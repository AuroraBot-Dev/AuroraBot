# AuroraBot vNext

AuroraBot 正在从冻结的旧系统重建。`legacy/` 保存历史实现与测试，只可作为迁移参考；除非明确要求，不得向其中新增功能或以其架构约束 vNext。

## Architecture authority

- `docs/rfc/` 是 vNext 的唯一设计基准。
- 已接受 RFC 高于 README、注释、配置样例和现有代码。
- 影响模块边界、事件、配置、扩展或模型调用契约的改动，必须先更新或新增 RFC。
- 当前首要目标是 RFC 0001 定义的最小闭环，而不是恢复旧功能。

## Project layout

```text
config/       TOML 主配置、领域配置与 profile 覆盖
docs/rfc/     RFC 0000—0005
legacy/       冻结的旧实现
src/kernel/   事件、工作区、图、周期、因果与状态
src/ai/       宽泛模型网关
src/localhost/ 本地业务服务与开发者调试接口
src/dashboard/ Dashboard 的后端路由/API 适配层
src/platform/ 平台生态适配与 AMP 归一化
src/apps/     内建原生 AMP-MCP 应用
src/nodes/    内建、自包含的认知节点
src/utils/    无上层依赖的通用工具
tests/        vNext 契约和集成测试
```

## Hard boundaries

- Kernel 只负责事件、状态、图调度、周期和因果边界；不决定认知内容，也不直接执行平台效果。
- Node 只能通过 Kernel API 读取上下文、请求声明过的能力并产出事件；不得直接写共享工作区、调用平台 Client 或绕过事件记录。
- Platform 将外部生态归一化为 AMP 输入，并执行 `effect.requested`；执行结果必须以新的 AMP 事件回到 Kernel。
- `localhost` 提供业务用例；`dashboard` 只提供路由/API 适配，不能绕过 `localhost` 直接操作 Kernel。
- `utils` 不得依赖 `kernel`、`ai`、`platform`、`nodes`、`localhost` 或 `dashboard`。

## Workspace and configuration

- Kernel 工作区固定为 `data/kernel/inbox/`、`process/`、`archive/`。
- 所有外部事件和运行时记录为 JSON；生产者必须临时写入后原子改名。
- 所有结构性配置使用 TOML；JSON 不得承担主配置职责。
- 密钥仅来自环境变量；`.env` 仅是本地开发辅助，不能定义结构或覆盖任意 TOML 值。

## Code conventions

- Python 3.12，包管理使用 `uv`。
- Ruff 行宽 120，LF，双引号；公开 API 提供类型注解，dataclass 优先 `slots=True`。
- 日志级别与边界见 `LOGGING.md`。
- 当前没有 vNext 可运行入口；不要把旧 `bot.py` 当作实现目标。
