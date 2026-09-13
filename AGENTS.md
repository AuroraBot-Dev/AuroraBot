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

文档按效力分层：

- `docs/rfc/0300-design-philosophy.md` 是设计思想：只陈述不变量与判断准则，不含实现坐标（包名、文件名、字段名、类名、协议修订号、事件名等）；仅当设计思想、语义不变量或边界本身改变时才修订。
- 其他 `docs/rfc/` 记录稳定的机制决策；`docs/architecture/` 记录现行实现结构，可随实现自由更新；`docs/reference/` 记录精确词汇与协议。
- `docs/` 是独立文档仓库的子模块；RFC 先在 docs 仓库提交，再由主仓库更新子模块指针。
- 仅当设计思想、语义不变量或边界改变时才更新 RFC；实现结构、配置字段、事件名等改动只更新 architecture/reference 与测试，不动 RFC。
- Python 源码和测试的注释与 docstring 不提具体 RFC 编号，直接说明局部不变量。

## Project layout

```text
config.example/ 随源码发布的完整配置模板；每个 TOML 对应一个 configuration 模块
config/         从模板复制的个人生效配置，始终由 Git 忽略
aurora/         项目级入口与配置解析
aurora/commands/       每个 CLI 命令一个自动发现模块
aurora/configuration/  每个 TOML 一个解析模块，引用 src/<pkg> 的配置 DTO 并导出唯一 CONFIG_SPEC
aurora/config.py       按注册顺序合并 TOML 为只读 AuroraConfig；同时实现 src.contracts.Settings
aurora/utils/          项目级进程、环境、日志、信号、平台、TOML 与包发现工具
src/utils/      无上层依赖的日志、时间、文本与序列化工具
src/contracts/  AgentTree、ChatMessage、Model、Tool、能力协议与组合内核公共值对象
src/kernel/     组合微内核：@module/ModuleSpec、依赖解析、拓扑装配、生命周期与发现源
src/runtime/    Bot 进程门面与装配入口：发现源、门面工厂、终端命令分派与文本呈现
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
panel/          独立前端子模块（后端已移除，仅保留前端与工具链）
scripts/        三平台安装脚本（linux/macos/windows）
assets/         多语言文案（zh-CN/ja-JP/en-US）
extensions/     本机 MCP 应用与本地插件运行时目录，始终由 Git 忽略
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
- Console 输入先作为 `console.input` 提交到 `aurora:console`，终端渲染输出不进入世界线；`/help`、`/clear`、`/quit`
  是本地命令，不进入组合内核。
- model id 是节点事实，必须显式进入每个 `ModelRequest`，不得由全局 runner 或 profile 隐式推导。
- `src/kernel` 是唯一组合机制：以契约类型为能力身份，`@module`/`ModuleSpec` 声明 `provides/requires/contributes/consumes`
  与可选 `prepare/activate/run/close`；依赖解析、冲突裁决、可选跳过、环检测与拓扑装配都在内核，内核不认识具体 `src` 子包。
- 每个 `src/<pkg>` 在 `module.py` 自描述唯一 `MODULE`；兄弟能力只经 `src.contracts` 的契约类型注入，模块之间不运行时相互
  import（类型位置允许 TYPE_CHECKING）。
- 发现源：随安装发布的 `src` 包、项目内被 Git 忽略的 `extensions/plugins/` 与 `aurorabot_plugin` entry point；同优先级冲突、
  缺失依赖与依赖环都在启动前失败。
- `aurora` 只负责 CLI 命令分发与配置解析：`configuration` 引用 `src/<pkg>` 的配置 DTO，`config` 合并为只读 `AuroraConfig`
  并实现 `src.contracts.Settings`；`aurora start` 只负责 `.env`、配置加载、进程日志与 SIGINT/SIGTERM，然后调用 `src.runtime`
  的装配入口，不含组合逻辑。
- `src/runtime` 是 Bot 进程门面与装配入口：发现模块声明、从冻结 `Assembly` 创建门面并接线 `TreeLauncher` 绑定；
  终端命令分派与文本呈现各自独立。
- 命令与配置模块按目录自动发现：新增并列项只增加该能力自己的配置模板、`configuration`/`src/<pkg>/module.py`/测试。
- 下层无项目语义的共享功能放入 `src.utils`；项目组合工具放入 `aurora.utils`；并列模块不得寄存彼此的工具函数。
- 依赖方向：`src.utils` 与 `src.contracts` 是最底层叶子，任何包都可以运行时直接引用；`src/kernel ← src/runtime`；功能 src 包
  运行时只依赖 contracts、utils 与自身，跨包能力只允许类型检查期（TYPE_CHECKING）引用，真正的能力调用靠内核注入的契约实例
  完成；`src ← aurora`；`src` 不导入 `aurora`。具体允许集由 `tests/test_dependency_boundaries.py` 固化。

## Current scope

当前实现 `src/kernel` 组合微内核、自描述 `src` 模块、LiteLLM Model、Console、cadence、只读 World Memory、MCP SDK 2.x 与 start
生命周期，以及 WorldJournal 持久化与 migration；`panel/` 子模块仅保留前端，后端链路已移除。
不实现自动记忆、Inbox、并发/抢占、通用 Platform、sandbox、费用体系，以及 MCP sampling、elicitation、roots、Tasks 或非文本结果注入。
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
- 测试必须离线、确定、无网络、无环境变量依赖；Model 和 Tool 使用 fake；除 WorldJournal 的临时 SQLite 集成测试外不使用数据库。
- 提交前运行 `uv run aurora check --fix`。
