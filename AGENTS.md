# AuroraBot

AuroraBot 是以 Bot 为主体的自主智能体框架：一切设计都以 Bot 为中心，Bot 拥有世界与森林，一棵 `AgentTree` 只是 Bot 的一次认知运行。
当前工作树只描述现行架构与实现；只保留完整最小循环和项目级组合骨架。

## Design philosophy

### 以 Bot 为中心设计一切

AuroraBot 把 Bot 当作世界的主体，而不是被调用的接口：她一直存在，拥有自己的人格、状态与边界，一切设计都围绕她的生活展开。这个原则落到架构上有三条：

- **她拥有世界，树只是她的运行**：Bot 持有追加式的世界提交（WorldJournal）与多棵 `AgentTree`。一棵树只是一次运行，不是与她平行的另一个主体；聊天、任务、委派都是她生活中的一次经历，经历结束，她仍然存在。
- **一切输入都有媒介**：任何影响她的变化都必须先成为一条世界事件。你发给她的消息要先作为 `console.input` 提交到她的世界，应用事件、MCP 上报、工具结果、时间的流逝也是如此。她不是在响应接口，而是在经历世界。
- **她理解之后才决定**：来自用户的消息不会因为来源就自动成为最高指令。她先理解发生了什么，再决定回应、行动、委派或保持安静；模型只负责理解与判断，外部行动必须经声明的 Tool 执行，结果再作为新事件回到她的世界。

## Architecture authority

- `docs/rfc/0300-unified-architecture-and-contracts.md` 是唯一设计基准。
- `docs/architecture/` 是按包拆分的实施架构说明；`docs/architecture/packages/package-baseline.md` 是新增模块/包的最低扩展成本基线。
- `docs/` 是独立文档仓库的子模块；RFC 先在 docs 仓库提交，再由主仓库更新子模块指针。
- 影响 AgentTree、四角色消息、模型/工具端口、配置或组合根的改动，必须先更新 RFC。
- Python 源码和测试的注释与 docstring 不提具体 RFC 编号，直接说明局部不变量。

## Project layout

```text
config.example/ 随源码发布的完整配置模板；每个 TOML 对应一个 configuration 模块
config/         从模板复制的个人生效配置，始终由 Git 忽略
aurora/         项目级入口、统一 Config/Composer、runtime 门面与项目工具
aurora/commands/       每个 CLI 命令一个注册模块
aurora/configuration/  每个 TOML 一个解析与注册模块
aurora/composition/    每个需构造实例的 src 子包一个注册模块
aurora/runtime/        AuroraRuntime 门面：全部 ops 端口、echo 输出与进程生命周期
aurora/utils/          项目级进程、环境、平台与 TOML 工具
ops/            统一 OperationSpec 目录、运行监测、限定配置改动与本地 Panel HTTP
ops/operations/       每个运行时包一个 JSON 化操作注册模块
ops/panel/      Panel 会话、Token 与本地 HTTP 后端
ops/utils/      ops 层的格式化与资源工具
src/utils/      无上层依赖的日志、时间、文本与序列化工具
src/contracts/  AgentTree、ChatMessage、Model 和 Tool 公共契约
src/agents/     不可变 AgentDefinition 目录与唯一解析
src/tools/      工具注册表与框架内建工具
src/prompt/     四角色 PromptAssembler
src/engine/     AgentTree 的确定性单循环
src/ai/         LiteLLM 模型网关与 Provider 协议映射
src/mcp/        MCP SDK 2.x 客户端适配、冻结工具目录与业务事件入口
src/world/      WorldJournal 唯一持久化实现与 migration
src/cadence/    世界提交驱动的主动节律
src/memory/     只读近期世界记忆快照
src/console/    输入先入世界线的本地异步终端
tests/          离线行为、组合与边界测试
docs/           文档站点与唯一 RFC 子模块
panel/          消费同一 ops 目录的独立前端子模块
scripts/        三平台安装脚本（linux/macos/windows）
assets/         多语言文案（zh-CN/ja-JP/en-US）
extensions/     本机 MCP 应用运行时目录，始终由 Git 忽略
```

## Core boundaries

- Bot 是唯一设计主体：一切能力、端口与扩展都从 Bot 的视角提出——Bot 拥有世界与森林，一棵 `AgentTree` 只是一次运行，不是 Bot 本身；
  引入任何新概念前先说明它如何服务 Bot，而不是服务某个抽象运行模型。
- Bot 的一次认知运行由一棵 `AgentTree` 表示；不再引入独立 Task、mailbox、Activity 或 continuation 作为平行运行模型。
- root 与 child 使用同一种 `AgentNode` 和循环。实例只因 prompt、初始 message、可见 tools 和 LLM model 不同。
- `ChatMessage` 只允许 `system`、`message`、`assistant`、`tool` 四种领域 role；只有 Provider adapter 可把
  `message` 映射成协议的 `user`。
- `PromptAssembler` 只装配上下文，不访问模型、工具、数据库或记忆服务；世界记忆由 `src.memory` 生成 `MemorySnapshot`，
  作为显式参数注入，不在 assembler 内持有读取端口。
- `AgentTreeRunner` 只执行给定树：依赖 contracts + agents + prompt + tools，并通过 `WorldJournal` 记录运行因果；普通 Tool 经端口执行，`delegate` 是唯一由 engine 解释的内建 Tool。
- `src/world` 是逻辑事件总线，代码上是叶子；`WorldReader / WorldWriter / WorldJournal` 端口只属于 contracts，其他包不得 import 实现。
- 世界提交归属哪个 scope 由提交方决定；world 只校验、编号和追加，不产生事件。
- `src/cadence` 只按世界提交请求唤起一棵 AgentTree；`src/memory` 只消费 `WorldReader` 生成 PromptAssembler 的显式输入；
  二者不得保存或解释另一套认知运行状态。
- Console 输入先作为 `console.input` 提交到 `aurora:console`，终端渲染输出不进入世界线。
- 每个运行时包在 ops 中拥有窄 RuntimePort 和 method/path + 斜杠入口，成功数据以 JSON 输出；未装配端口返回 `NOT_AVAILABLE`。
- model id 是节点事实，必须显式进入每个 `ModelRequest`，不得由全局 runner 或 profile 隐式推导。
- `aurora` 是唯一项目组合层：`configuration` 只产生纯 DTO，`composition` 分阶段构造 Prompt、Engine 与 Runtime，
  `commands` 按模块注册 CLI，`main.py` 只分派。
- 命令、配置和组件都通过目录入口的显式元组注册；新增并列项只增加一个模块和一条注册记录。
- 下层无项目语义的共享功能放入 `src.utils`；项目组合工具放入 `aurora.utils`；并列模块不得寄存彼此的工具函数。
- 依赖方向：`src.utils` 与 `src.contracts` 是最底层叶子；`agents/prompt/ai/console/cadence/memory/mcp/world` 只依赖
  contracts、自身与 utils；`tools ← engine ← aurora`，`console ← aurora`、`ops ← aurora`；`src` 不导入 `aurora` 或 `ops`，
  ops 不导入 src 或 aurora。具体允许集由 `tests/test_dependency_boundaries.py` 固化。

## Current scope

当前实现 ops（含本地 Panel HTTP 后端与 Token 登录）、LiteLLM Model、Console、cadence、只读 World Memory、MCP SDK 2.x 与 start 生命周期，
以及 WorldJournal 持久化与 migration；panel 子模块是消费同一 ops 目录的 Vue 前端；
不实现 Panel 附件与 WebSocket、自动记忆、Inbox、并发/抢占、通用 Platform、sandbox、费用体系，以及 MCP sampling、elicitation、roots、Tasks 或非文本结果注入。
引入这些能力前，先给出围绕 AgentTree 的真实用例、不变量和独立测试。

## Language and text

- 项目文本以简体中文为默认和权威版本，包括 CLI 帮助与输出、错误说明、配置注释、默认 Prompt、README 和设计文档。
- 代码标识符、协议字面量、外部 API 字段和必要的技术术语可以使用英文；面向人的完整句子优先使用中文。
- 英文与日文翻译可以保留，但中文内容先更新；翻译冲突或落后时以中文为准。
- 用户可见文本只描述当前身份、能力和限制，不使用实验、重构、旧版、迁移等历史阶段叙事。

## Runtime and quality

- Python 3.12，使用 uv。
- Ruff 行宽 120，LF，双引号；公开 API 有类型注解；值对象优先 frozen + slots dataclass。
- 单个源码文件不超过 600 行, 数据模型定义（ORM/DataClass）如 SQLAlchemy 或 Pydantic 模型，如果只是字段声明（无逻辑），允许 1000+ 行，因为它们是声明式配置。
- 不以 lint ignore 掩盖核心复杂度。
- 测试必须离线、确定、无网络、无环境变量依赖；Model 和 Tool 使用 fake；除 WorldJournal 与 Panel 会话的临时 SQLite 集成测试外不使用数据库。
- 提交前运行 `uv run aurora check --fix`。
