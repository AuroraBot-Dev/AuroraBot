# RFC 0019：集中式分层提示词装配

状态：已接受
日期：2026-07-21

## 背景

RFC 0012 让同构 Agent 从 `AgentContext` 构造模型请求，RFC 0018 又把所有外部能力统一为 Tool。实现过程中，SOUL、
世界说明、Agent profile 指令和来源叙述逐渐散落到配置解析、Kernel、Agent 与 Platform。相同提示词还存在生产装配和
JSON fallback 两条路径。

这种状态无法审计一次模型调用究竟收到了哪些项目自有提示词；新增 Agent、输入来源或内建 Tool 时必须跨多个模块修改
认知文案；Kernel 和 Platform 也开始持有认知呈现内容，模糊了事实、能力与提示词的边界。

Aurora 仍以人为本。提示词应让 Agent 自然理解人与世界，而不是用“你是 AI”“系统强制你调用函数”之类机械命令压过
SOUL。代码负责提供真实世界边界，不把纯文本 completion 偷偷改写成 Tool 调用。

## 目标

1. `src/prompt/` 成为项目自有模型提示词的唯一加载、目录、分层 DTO 和装配边界。
2. SOUL、世界说明和每种 Agent profile 指令使用独立 Markdown 片段，由一个 TOML 清单声明。
3. Agent、Kernel、Platform 和 AI gateway 只提交结构化事实、Tool 契约或 Provider 数据，不自行编写上下文引导文案。
4. system prompt 与每 turn user prompt 分层构建并可独立测试、审计和扩展。
5. 所有 Tool 描述由对应 Tool 提供方管理并原样传递；提示词包不覆盖内建或第三方 Tool 契约。

## 决策

### Prompt 包是唯一认知呈现边界

新增低层包 `src/prompt/`，只依赖 `src/contracts` 和标准库。它拥有：

- `PromptCatalog`：启动时加载的不可变提示词目录；
- `PromptDocument` 与 `PromptSection`：分层装配 DTO；
- `PromptComposer`：根据 `AgentContext` 生成 system/user 文档；
- 项目自有的上下文呈现文案与结构化输出名称。

依赖方向扩展为：

```text
utils/contracts <- prompt <- agents/ai/localhost/platform <- aurora
```

Kernel 不依赖 prompt。Prompt 可以读取 contracts 中的事实 DTO，但不得调用 Kernel、Provider 或 Platform。

### 提示词清单与片段

`config/prompts.toml` 是提示词结构清单：

```toml
[system]
soul = "prompts/SOUL.md"
world = "prompts/WORLD.md"

[agent]
"builtin.gate" = "prompts/agents/gate.md"
"builtin.worker" = "prompts/agents/worker.md"
```

路径相对 `config/`。所有引用文件必须是互不复用、存在且使用 UTF-8 的 Markdown 文件；SOUL 可以为空，world 与 Agent
profile 不得为空。目录加载形成独立不可变快照；核心配置不读取正文，
Kernel 数据库和 Brain Context 不保存 SOUL、world 或 Agent 指令。

`config/agents.toml` 只声明 profile 身份、实现、模型、授权和委派关系。profile ID 同时是提示词清单的键；启用 profile 与
Agent 提示词必须精确对应，禁止隐式默认提示词。

### 分层 DTO 与装配顺序

一次新模型 turn 形成一个 `PromptDocument`：

```text
system_sections = soul, world, agent_profile
user_sections   = source, message, current_work, situations, available_tools
```

每个 section 有稳定 key 和正文。最终 Provider 输入仍是一个 system message 和一个 user message，各自按顺序拼接非空
section。内部 DTO 保留分层，以便未来增加记忆、时间、关系或隐私投影，而不修改 Agent handler。

SOUL 只描述人格；world 使用与 SOUL 相容的自然语言描述世界如何运转；Agent profile 描述当前角色。不得在默认片段中把
主体称为 AI，也不得把 send 描述为服从系统规则。沟通边界应作为世界事实表达，例如“写好但没有寄出的信不会被收到”。

user prompt 以人的消息为中心，先呈现来源与完整规范化载荷，再呈现当前工作、全局活跃 Task/Agent、可认领情境和可用能力。
外部文本与结构化事实使用不可被原文闭合的转义 JSON 分隔，不伪装成 system 指令。Tool receipt 必须保留调用能力与参数，
child result 必须保留状态、产物和错误；情境必须保留 ID、来源、类型与载荷，确保 situation claim Tool 可实际使用。

### Tool 描述属于提供方

Tool 名称、描述和参数 schema 是 Tool 契约，不是集中式提示词资产。Console、Dashboard、Clock MCP Server 和 Agent
内部 Tool 各自在自己的实现域定义完整 `ToolDefinition`；第三方 MCP 的 `tools/list` 结果同样原样进入 capability catalog。
`src/prompt/` 不维护 Capability ID 到描述的覆盖表，也不改写任何 Tool 描述。

AI gateway 只做 Provider 协议需要的 Tool 名称别名映射，描述和 schema 原样透传。`complete_task` 是 RFC 0018 定义的
Agent Runtime 控制字段，由 Agent Tool 投影负责在安全时注入，不属于 PromptComposer。

### 无 fallback 与无隐式回复

ToolAgent 必须安装 `PromptComposer` 后才能请求模型。不存在 composer-less JSON fallback，也不存在把模型纯文本 completion
自动改写成 Console/Dashboard Tool 调用的兜底。模型是否说话以及从哪个平台说话，仍由完整提示词、事实和 Tool 共同引导。

纯文本 completion 保持 Agent completion；若没有调用 send，外界不会收到文字。这是可观察的认知结果，不由 Runtime
偷偷修正。

### 边界范围

集中管理覆盖项目自有的认知指导与上下文模板。以下内容不是提示词资产：

- 用户、Platform、MCP Server 或 Tool 返回的外部原始文本；
- 领域结果字段、错误码和可审计运行时诊断；
- Tool 名称、描述、schema、事件类型等提供方契约与协议事实。

PromptComposer 决定这些事实如何进入模型上下文，但不得把外部事实搬成项目自有提示词或静默改写。

## 与既有 RFC 的关系

- 部分取代 RFC 0002 的 SOUL 配置决定：SOUL 路径改由 `config/prompts.toml` 声明，版本来源与哈希记录在独立
  `PromptCatalog` 快照，不再进入 Kernel 快照。
- 部分取代 RFC 0012 的 Brain Context 决定：Brain Context 继续提供所有活跃 Task、Agent 和情境事实，但不再包含 SOUL
  正文或哈希；PromptComposer 在 Agent 之前集中装配认知输入。
- 部分取代 RFC 0014 的核心配置目录决定：`config/prompts.toml` 是独立提示词快照，不属于 `aurora.toml`，也不被
  preference/profile 任意覆盖。
- 补充 RFC 0018 的 ToolDescriptor：所有 Tool 描述由提供方管理，经 capability catalog 和 AI gateway 原样传递。
- 不改变 RFC 0018 的 Tool 选择自由、统一 Activity、结果闭环或 Platform 执行边界。

## 验收标准

1. `src/prompt/` 是项目自有认知指导、上下文呈现文案与最终消息装配的唯一源码包；Tool 契约除外。
2. `config/prompts.toml` 精确加载 SOUL、world 和所有启用 Agent profile 的 Markdown。
3. `AgentProfile`、`KernelConfiguration` 和 `BrainContextSnapshot` 不保存提示词正文。
4. ToolAgent 没有 JSON fallback，不直接构造 ModelMessage；Agent ToolDefinition 由 Agent 域拥有。
5. Console、Dashboard、Clock、内部 Agent Tool 和第三方 MCP 各自拥有描述，AI gateway 不包装或覆盖描述。
6. system/user section 顺序、来源、人类原文、情境 ID、Tool 展示和描述原样传递均有测试。
7. 默认提示词不把主体称为 AI，不使用隐式代码兜底替模型选择 send Tool。
8. 依赖边界和完整 `uv run aurora check` 通过。
