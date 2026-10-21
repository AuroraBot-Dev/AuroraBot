# AuroraBot

AuroraBot 是以 Bot 为主体的自主智能体框架：一切设计都以 Bot 为中心，Bot 拥有世界与森林，一棵 `AgentTree` 只是 Bot 的一次认知运行。
当前工作树描述持久主体、独立节律与记忆模型、完整认知循环和可扩展外围环境的现行实现。

## Design philosophy

### 以 Bot 为中心设计一切

AuroraBot 把 Bot 当作世界的主体，而不是被调用的接口：她一直存在，拥有自己的人格、状态与边界，一切设计都围绕她的生活展开。这个原则落到架构上有三条：

- **她拥有世界，树只是她的运行**：Bot 持有追加式的世界提交（WorldJournal）与多棵 `AgentTree`。一棵树只是一次运行，不是与她平行的另一个主体；聊天、任务、委派都是她生活中的一次经历，经历结束，她仍然存在。
- **一切输入都有媒介**：任何影响她的变化都必须先成为一条世界事件。你发给她的消息要先作为 `console.input` 提交到她的世界，应用事件、MCP 上报、工具结果、时间的流逝也是如此。她不是在响应接口，而是在经历世界。
- **她理解之后才决定**：来自用户的消息不会因为来源就自动成为最高指令。她先理解发生了什么，再决定回应、行动、委派或保持安静；模型只负责理解与判断，外部行动必须经声明的 Tool 执行，结果再作为新事件回到她的世界。

## Architecture authority

文档按效力分层：

- `apps/docsite/src/rfc/0300-design-philosophy.md` 是设计思想：只陈述不变量与判断准则，不含实现坐标（包名、文件名、字段名、类名、协议修订号、事件名等）；仅当设计思想、语义不变量或边界本身改变时才修订。
- 其他 `apps/docsite/src/rfc/` 记录稳定的机制决策；`apps/docsite/src/architecture/` 记录现行实现结构，可随实现自由更新；`apps/docsite/src/reference/` 记录精确词汇与协议。
- `apps/docsite/src/` 中的文档与应用、运行时代码由同一仓库管理，相关改动一起提交。
- 仅当设计思想、语义不变量或边界改变时才更新 RFC；实现结构、配置字段、事件名等改动只更新 architecture/reference 与测试，不动 RFC。
- Python 源码和测试的注释与 docstring 不提具体 RFC 编号，直接说明局部不变量。

## Project layout

Python 采用 src layout：`src/` 是源码目录，`aurora_cli` 与 `aurora_bot` 是同一发行包中的两个导入包。
uv 管理 Python，pnpm workspace 管理前端；两者独立构建、共享仓库。运行测试前先通过 uv 安装项目。

```text
config.example/ 随源码发布的完整配置模板；每个 TOML 对应一个 configs 模块
config/         从模板复制的个人生效配置，始终由 Git 忽略
src/aurora_cli/     项目级入口与配置解析
src/aurora_cli/commands/       每个 CLI 命令一个自动发现模块
src/aurora_cli/configs/        每个 TOML 一个解析模块，引用 src/aurora_bot/<pkg> 的配置 DTO 并导出唯一 CONFIG_SPEC
src/aurora_cli/contracts/      配置与命令的公共值对象契约；并列模块只从这里导入声明类型
src/aurora_cli/configurator.py 按注册顺序合并 TOML 为只读 AuroraConfig；同时实现 aurora_bot.contracts.Settings
src/aurora_cli/utils/          项目级进程、环境、日志、信号、平台、TOML 与包发现工具
src/aurora_bot/utils/      无上层依赖的日志、时间、文本与序列化工具
src/aurora_bot/contracts/  公共值对象、常量与贡献契约；跨包能力端口按提供方放在 src/aurora_bot/contracts/pkgs/<pkg>.py
src/aurora_bot/kernel/     组合微内核：@module/ModuleSpec、依赖解析、拓扑装配、生命周期与发现源
src/aurora_bot/runtime/    Bot 进程门面与装配入口：发现源、门面工厂、终端命令分派与文本呈现
src/aurora_bot/bot/        持久目标、检查点、未来活动与版本化主体状态操作
src/aurora_bot/clock/      与主体独立装配的持久活动兑现服务
src/aurora_bot/agents/     不可变 AgentDefinition 目录与唯一解析
src/aurora_bot/tools/      工具注册表与框架内建工具
src/aurora_bot/prompt/     四角色 PromptAssembler
src/aurora_bot/engine/     AgentTree 的确定性单循环
src/aurora_bot/ai/         LiteLLM 模型网关与 Provider 协议映射
src/aurora_bot/mcp/        MCP SDK 2.x 客户端适配、冻结工具目录与业务事件入口
src/aurora_bot/world/      WorldJournal 唯一持久化实现与 migration
src/aurora_bot/cadence/    世界与时间驱动的主动调度、判断日志与隐状态恢复
src/aurora_bot/rhythm/     规则与 GRU 节律策略、训练、验证及权重加载
src/aurora_bot/memory/     时间正确的经历读取、必要连续性、集合组装与反馈审计
src/aurora_bot/memory_model/ 规则与 TGN 排序、训练、验证与可重建图投影
src/aurora_bot/resources/  资源版本、别名、契约与动态提供者的统一目录
src/aurora_bot/scopes/     世界域声明、分类与范围校验
src/aurora_bot/operations/ 命令与查询路由、幂等回执及未知效果恢复边界
src/aurora_bot/artifacts/  固定内容存储、校验与有界读取
src/aurora_bot/resource_content/ 实际资源定义正文的生命周期归档
src/aurora_bot/instances/  从世界事实发现认知实例及其确定历史版本
src/aurora_bot/console/    输入先入世界线的本地异步终端
tests/          离线行为、组合与边界测试
apps/docsite/   VitePress 2 文档站，正文位于 src/
apps/panel/     Vue 面板，页面位于 src/
packages/       前端共享库（保留各包原有授权）
tooling/        共享 TypeScript、构建与检查配置包
apps/landing/   Vue + TypeScript 落地页，多语言文案与静态资源
docs/           不进入文档站的仓库文档（贡献指南、行为准则等）
scripts/        三平台安装脚本与 TypeScript .mts 工程脚本
extensions/     本机 MCP 应用与本地插件运行时目录，始终由 Git 忽略
```

## Core boundaries

- Bot 是唯一设计主体：一切能力、端口与扩展都从 Bot 的视角提出——Bot 拥有世界与森林，一棵 `AgentTree` 只是一次运行，不是 Bot 本身；
  引入任何新概念前先说明它如何服务 Bot，而不是服务某个抽象运行模型。
- Bot 的一次认知运行由一棵 `AgentTree` 表示；不再引入独立 Task、mailbox、Activity 或 continuation 作为平行运行模型。
- root 与 child 使用同一种 `AgentNode` 和循环。实例只因 prompt、初始 message、可见 tools 和 LLM model 不同。
- `ChatMessage` 只允许 `system`、`message`、`assistant`、`tool` 四种领域 role；只有 Provider adapter 可把
  `message` 映射成协议的 `user`。
- `PromptAssembler` 只装配上下文，不访问模型、工具、数据库或记忆服务；世界记忆由 `aurora_bot.memory` 生成 `MemorySnapshot`，
  作为显式参数注入，不在 assembler 内持有读取端口。
- `AgentTreeRunner` 只执行给定树，通过 contracts 注入的模型、原型、提示词、工具、记忆和世界端口工作；
  普通 Tool 经端口执行，内建 `delegate` 返回的 `DelegationRequest` 由 engine 应用为树操作。
- `src/aurora_bot/world` 是逻辑事件总线，代码上是叶子；`WorldReader / WorldWriter / WorldJournal` 端口只属于 contracts，其他包不得 import 实现。
- 世界提交归属哪个 scope 由提交方决定；world 只校验、编号和追加，不产生事件。
- `src/aurora_bot/bot` 是目标与恢复状态的唯一所有者，`src/aurora_bot/clock` 兑现已登记活动；二者可独立替换，公开命令和默认时钟使用同一选中主体。
- `src/aurora_bot/cadence` 按世界变化、时间和主体压力调用 `RhythmPolicy`，持久记录判断与循环隐状态，再请求唤起 AgentTree；
  `src/aurora_bot/memory` 通过 `WorldReader`、主体状态和 `MemoryPolicy` 生成显式快照，不另建认知运行模型。
- 记忆内容、主体检查点和模型投影分开保存；时间与游标决定可见历史，后续反馈不能泄漏到过去的查询。
  上下文先保留必要状态、证据和完整交互，必要内容超限时在模型或行动效果前失败，不截断关键约束。
- Console 输入先作为 `console.input` 提交到 `aurora:world/console`，终端渲染输出不进入世界线；`/help`、`/clear`、`/quit`
  是本地命令，不进入组合内核。
- model id 是节点事实，必须显式进入每个 `ModelRequest`，不得由全局 runner 或 profile 隐式推导。
- `src/aurora_bot/kernel` 是唯一组合机制：以契约类型为能力身份，`@module`/`ModuleSpec` 声明 `provides/requires/contributes/consumes`
  与 `prepare/construct/activate/ready/run/drain/close` 等声明阶段；依赖解析、冲突裁决、可选跳过、环检测与拓扑装配都在内核，
  内核不认识具体 `aurora_bot` 子包。接线和生命周期跟随实际选中能力，失选默认提供方不产生准备效果。
- 模组使用 `namespace:kernel/module/path`，发布版本与内核 API 范围分别声明，兼容性在准备效果前校验。
  清单归档固定声明而非可执行环境；目录、错误和生命周期监督都保留完整模组身份。
- 资源使用 `namespace:domain/kind/path`，定义版本、别名和运行实例分别记录；实际模型、原型、Prompt、工具与过程版本进入世界审计。
  提供方资源身份与 SDK 路由分离，`sdk_provider` 表达协议前缀，不从对象显示文本或嵌套资源路径推导请求模型。
- 领域操作由同一份版本化定义生成结构化工具和终端入口；请求、回执与因果持久保存，大对象使用固定内容引用。
  已开始且效果未知的非幂等操作不自动重放；模型曝光、自评和成功回执各自表达不同事实。
- 每个 `src/aurora_bot/<pkg>` 在 `module.py` 自描述唯一 `MODULE`；兄弟能力只经 `aurora_bot.contracts` 的契约类型注入，模块之间不运行时相互
  import（类型位置允许 TYPE_CHECKING）。
- 发现源：随安装发布的 `aurora_bot` 包、项目内被 Git 忽略的 `extensions/plugins/` 与 `aurorabot_plugin` entry point；同优先级冲突、
  缺失依赖与依赖环都在启动前失败。
- `aurora_cli` 只负责 CLI 命令分发与配置解析：`configs` 引用 `src/aurora_bot/<pkg>` 的配置 DTO，`configurator` 合并为只读 `AuroraConfig`
  并实现 `aurora_bot.contracts.Settings`；配置与命令的公共值对象放在 `aurora_cli.contracts`，并列模块只从这里导入声明类型；
  `aurora start` 只负责 `.env`、配置加载、进程日志与 SIGINT/SIGTERM，然后调用 `aurora_bot.runtime`
  的装配入口，不含组合逻辑。
- `src/aurora_bot/runtime` 是 Bot 进程门面与装配入口：发现模块声明、从冻结 `Assembly` 创建门面并接线 `TreeLauncher` 绑定；
  终端命令分派与文本呈现各自独立。
- 命令与配置模块按目录自动发现：新增并列项只增加该能力自己的配置模板、`configs`/`src/aurora_bot/<pkg>/module.py`/测试。
- 下层无项目语义的共享功能放入 `aurora_bot.utils`；项目组合工具放入 `aurora_cli.utils`；并列模块不得寄存彼此的工具函数。
- 依赖方向：`aurora_bot.utils` 与 `aurora_bot.contracts` 是最底层叶子，任何包都可以运行时直接引用；`src/aurora_bot/kernel ← src/aurora_bot/runtime`；功能 aurora_bot 包
  运行时只依赖 contracts、utils 与自身，跨包能力只允许类型检查期（TYPE_CHECKING）引用，真正的能力调用靠内核注入的契约实例
  完成；`aurora_bot ← aurora_cli`；`aurora_bot` 不导入 `aurora_cli`。依赖边界由 `tests/foundation/test_dependency_boundaries.py` 按约定校验：叶子包只依赖自身，
  其他包可依赖 contracts 与 utils，机制包额外可依赖 kernel；新增能力包无需修改该测试。

## Current scope

当前实现持久 Bot 主体与未来安排、规则和可训练 GRU 节律、规则和可训练 TGN 记忆、统一资源和领域操作、可发现版本化模组、
LiteLLM Model、Console、MCP SDK 2.x、完整 start 生命周期、世界持久化与内容归档；`apps/panel/` 仅包含前端应用。
不实现自动摘要、自动在线参数训练、Inbox、并发/抢占、通用 Platform、sandbox、费用体系，以及 MCP sampling、elicitation、roots、Tasks 或非文本结果注入。
引入这些能力前，先给出围绕 AgentTree 的真实用例、不变量和独立测试。
受控离线训练证明模型使用历史且可优化，不等同于真实任务收益；记忆索引和图投影仍随保留历史增长。

## Language and text

- 项目文本以简体中文为默认和权威版本，包括 CLI 帮助与输出、错误说明、配置注释、默认 Prompt、README 和设计文档。
- 代码标识符、协议字面量、外部 API 字段和必要的技术术语可以使用英文；面向人的完整句子优先使用中文。
- 英文与日文翻译可以保留，但中文内容先更新；翻译冲突或落后时以中文为准。
- 用户可见文本只描述当前身份、能力和限制，不使用实验、重构、旧版、迁移等历史阶段叙事。

## Runtime and quality

- Python 3.12，使用 uv；Vue 应用与 TypeScript 脚本使用 Node.js 24、pnpm 12，根目录统一 workspace 与锁文件。
- Ruff 行宽 120，LF，双引号；公开 API 有类型注解；值对象优先 frozen + slots dataclass。
- 单个源码文件不超过 600 行, 数据模型定义（ORM/DataClass）如 SQLAlchemy 或 Pydantic 模型，如果只是字段声明（无逻辑），允许 1000+ 行，因为它们是声明式配置。
- 不以 lint ignore 掩盖核心复杂度。
- 测试必须离线、确定、无网络、无环境变量依赖；Model 和 Tool 使用 fake；除 WorldJournal 的临时 SQLite 集成测试外不使用数据库。
- pytest 使用 importlib 模式，测试按能力分目录，专用辅助代码随对应能力放置，跨能力替身放在 `tests/support/`，均经 `tests.*` 显式导入。
- 测试优先保护认知循环、持久化一致性、幂等与未知效果恢复、权限和路径边界、凭据脱敏及记忆时间正确性。
  简单字段转发、展示格式、常量和已有场景重复覆盖的分支不要求单独测试；不为提高覆盖率补用例。
- 日常检查不采集覆盖率；`uv run aurora check --test --coverage` 按需采集，CI 总体下限为 20%。
  该值是最低门槛，不是删减目标；关键行为的测试由风险决定，不由代码占比决定。
- 提交前运行 `uv run aurora check --fix`。
