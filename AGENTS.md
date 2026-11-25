## 编码规范

- 以**中文**为项目的主要注释、提交和 docstring 语言。
- 遵循小步提交规范，不在暂存区留存大量未提交更改。使用谷歌风格的提交信息，以动词开头，说明本次提交的目的。
- 新功能须在 `feat/<功能名>` 分支上开发，完成相关验证后通过 PR 合并到 `main`，不直接向 `main` 提交新功能。
- 开始工作前检查工作区和暂存区；提交包含本任务范围和在任务范围内的用户的修改，不夹带其他任务的修改。
- 不编写过程解释性注释，直接描述当前职责、行为和约束，不在代码中叙述改动历史。
- 更改 README.md 或 AGENTS.md 需要用户确认；用户明确要求修改该文件即视为确认，不重复询问。
  - README.md 一般保持稳定，不轻易改动。
  - 可以捕捉用户提出的要求，并询问是否记录到 AGENTS.md。
- 变更说明和验收记录写入[变更文档](docs/CHAGELOG.md)，不另外创建过程记录；用户明确指定独立文档时按指定位置编写。
- 拆包或调整接口时同步处理依赖、公共 ID、插件入口、配置、消费者、示例和文档，不留下未经要求的兼容别名、转发层或重复实现。
- 涉及 Github 操作的行为优先通过 gh-cli 完成.

## 项目结构

```text
.
├── packages/
│   ├── aurora_core/           # 微内核
│   ├── aurora_config/         # 配置声明、校验、TOML 模板与加载服务
│   ├── aurora_control/        # 执行契约与控制组合
│   ├── aurora_agent/          # ReAct、模型调用、工具执行与运行调度
│   ├── aurora_adapter/        # 模型协议、模型供应商与 MCP 适配
│   ├── aurora_bot/            # 默认装配、配置与产品入口
│   ├── aurora_cli/            # 命令行交互
│   ├── aurora_api/            # HTTP / WS 传输
│   ├── aurora_logging/        # 日志配置
│   ├── aurora_world/          # 世界来源、事件归档与环境观察
│   └── aurora_client/         # TS 共享 ctx 访问与连接
├── apps/
│   ├── aurora_tui/            # OpenTUI 终端界面
│   ├── aurora_panel/          # Vue Web 界面
│   ├── docsite/               # 文档站
│   └── landing/               # 落地页
├── docs/                     # 设计与公共 ID 文档
├── examples/                 # 首次安装配置助手：朴素 ReAct + terminal MCP
├── scripts/                  # 开发与按需生成脚本
├── tooling/                  # TS、lint 与样式工具共享配置
└── tests/
    ├── contract/
    └── e2e/
```

## 包边界

| 包 | 职责与约束 |
| --- | --- |
| `aurora_core` | 提供 ID、登记、ctx、订阅、连接、调用、生命周期和持久化机制；不承担 TOML 加载、配置 schema 策略、模型或业务流程控制 |
| `aurora_config` | 基于 core 提供配置声明、结构及关联校验、模板文件处理和 config 阶段服务；core 不反向依赖配置包 |
| `aurora_control` | 提供执行身份、状态绑定、插头插槽及 Serial、Branch、While、Parallel；仅依赖 core，不依赖 agent 或模型 |
| `aurora_adapter` | `model` 提供模型协议、能力声明、供应商适配与模型配置，`mcp` 提供外部协议及工具/世界桥；SDK 和桥依赖按 extra 安装，基础包仅依赖 core |
| `aurora_agent` | 提供 ReAct、模型调用、工具执行、默认阶段和 AgentRuntime；不依赖 bot、CLI 或 API |
| `aurora_bot` | 提供默认配置、产品装配、资源所有权、运行操作与命令；使用 agent，不复制 agent 的执行机制 |
| `aurora_cli` / `aurora_api` | 提供宿主、命令交互与 HTTP/WS 传输；不重复实现 agent 业务语义 |
| `aurora_logging` / `aurora_world` | 分别提供日志配置与世界来源、事件归档及有界环境观察；主动调度由 bot 的 cadence 接入 |
| `aurora_client` / `apps/*` | 客户端复用后端 ctx 语义，界面与静态站点不承担 Python 插件装配 |

执行依赖方向为 `bot → agent → control → core`；agent 和 bot 也可直接使用 core 与 aurora_adapter.model。agent 仅依赖 adapter 基础包；bot 使用 litellm extra；MCP 的工具、世界和产品桥通过独立 extra 与插件显式启用。配置能力通过 aurora_config 接入。独立 `aurora_harness` 是后续目标，不提前引入尚无实际消费者的框架抽象。

## 公共 ID 与插件

- ID 格式为 `<namespace>:<domain>/<local_path>`。公开定义按所属包命名：`org.aurora.core`、`org.aurora.config`、`org.aurora.control`、`org.aurora.agent`、`org.aurora.bot` 等。
- control 和 agent 的定义不能放在 bot 命名空间。bot 装配分配的配置、消息、引导、运行及工作状态地址仍归 bot，由状态绑定注入 agent。
- 插件发现分组为 `aurora.plugins`；entry point 名称与 `Plugin.name` 一致。控制入口为 `aurora_control`，agent 入口为 `aurora_agent.model`、`aurora_agent.react`、`aurora_agent.tools`、`aurora_agent.react_defaults`。
- 适配包名使用单数 `aurora_adapter`，模型入口为 `aurora_adapter.model`，MCP 入口为 `aurora_adapter.mcp` 及其桥插件；公共定义统一归属 `org.aurora.adapter`，local_path 按 model/mcp 区分。
- 安装包与启用插件分开；`requires` 只校验依赖插件已显式启用，不隐式加载依赖。只使用执行契约不要求启用四种控制组件。
- 定义身份、实例身份、run_id 与 execution_id 分开管理。调用等待决定执行结束，不能用残留状态推断调用完成。
- ID 或插件名变更须说明配置和快照的影响，不自动改写或删除用户数据；不要为通过恢复测试而静默忽略未登记的状态。

## 配置与运行约定

- 配置声明、模板和通用校验使用 `aurora_config`。插件通过 `ConfigSpec`、`ConfigSchema`、`ConfigTemplate` 和 `config_entries` 声明配置及对应的非持久状态，避免各包重复实现加载和默认值处理。
- TOML 是配置的持久来源；ctx 中的配置状态设置 `persistent=False`。运行期覆盖不自动写回文件，不把配置混入业务快照。
- 模板使用包内 `config.toml` 或 `config.tomls/`，同一包不同时提供两种形式；发布时包含模板资源。只复制缺失的用户文件，不覆盖已有配置。
- 宿主在恢复业务状态后执行 config 阶段，完成配置校验与注入，再执行 prepare/start。资源在配置就绪后创建；插件发现和定义查询不启动模型、工具或后台任务。
- 运行期凭证单独解析，不进入 TOML 模板、ctx、快照或日志。
- 每个 agent 实例只有一个调度所有者。AgentRuntime 的 execute 等待激活和清理完成，is_executing 覆盖整个占用期间；引导 progress 表示已接纳，不表示业务完成。
- 等待者取消不隐式取消 agent；显式取消须等待收尾。关闭时停止接收工作、结束自有任务、关闭工具与模型，再由宿主完成最终落盘。
- 恢复状态不代表透明续跑；未完成工具动作不自动重试，避免重复副作用。状态保留与裁剪由宿主明确，不由 core 推断。

## 开发与验证

Python 使用 uv workspace，版本要求见各包 pyproject.toml；Node 与 pnpm 版本以根 package.json 为准。

```powershell
# 安装 Python 工作区
uv sync --locked --all-packages
# 日常检查：格式、lint、Python/TypeScript 类型与快速边界测试
uv run --locked aurora check
# 完整检查：另含包内单测、前端、原生终端与长耗时集成测试
uv run --locked aurora check --full
# 按影响范围先运行针对性测试
uv run --locked pytest packages/aurora_agent/tests/unit/test_agent_runtime.py tests/e2e/test_package_boundaries.py -q
# 验证分发包与资源
uv build --all-packages --wheel --out-dir build/wheels
```

- 根据改动选择有意义的验证。日常 `aurora check` 只收集快速边界测试，`--test` 跳过静态检查，`--full` 显式启用完整测试，`--coverage` 也使用完整测试范围。纯文档修改检查链接与差异，不为此运行无关测试；涉及跨包契约、生命周期或配置行为时完成相关回归和 `aurora check --full`。
- 新增测试须覆盖现有用例无法验证的关键行为或真实缺陷，优先扩展、合并或替换既有用例，并在变更说明中交代独有价值；不为同一行为堆叠跨层重复测试、同类边界枚举或参数笛卡尔积，不添加仅复述实现步骤的断言，集成测试只保留代表链路。新增或扩大测试范围后，须在依赖已安装的同一开发环境实测完整命令墙钟时间，确保 `aurora check` 不超过 15 秒、`aurora check --full` 不超过 60 秒；超预算优先精简重复覆盖或改用可控夹具，不通过跳过检查、削弱有效断言或继续增加 worker 数规避。
- 拆包、依赖或分发内容变更还需验证 wheel；在干净环境中确认 control 无需 agent/模型包，agent 无需 bot/CLI/API。工作区可导入不能代替安装验收。
- 包级单元测试和协议测试分别位于 `packages/<包>/tests/unit`、`packages/<包>/tests/contract`；跨包契约测试位于根目录 `tests/contract`，工作区、真实进程及跨包集成测试位于根目录 `tests/e2e`。不通过删除有效断言或扩大容错来掩盖失败。
- `examples` 只保留 `onboarding` 安装配置助手，使用正式 ReAct 与 terminal MCP；不默认启用 QQ、世界订阅或决策模型。`examples/START.md` 保持为首次启动短指南，详细配置与操作说明放入 `docs`。旧离线应用仅作为 `tests/fixtures/runtime_apps` 回归夹具保留，不作为用户示例。
- 真实模型验收使用当前 CLI 和独立数据目录中的宿主、模型及工具配置，须由用户明确要求调用供应商；普通回归使用假模型或模拟传输，不因检查代码而自行调用真实服务。

## 参考入口

- [当前文档索引](docs/INDEX.md)
- [示例启动指南](examples/START.md)
- [架构设计](docs/aurorabot-design-v0.2.3.md)
- [公共 ID 目录](docs/aurorabot-id-catalog-v0.2.3.md)
- [拆包评估](docs/aurora_agent_extraction_assessment.md)
- [变更与验收记录](docs/CHAGELOG.md)

文档中的规划内容不等于已实现能力。发生不一致时先核对当前代码、插件清单和测试，不照搬历史交接文档中的待办。
