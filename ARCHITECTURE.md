# AuroraBot 架构实施说明

AuroraBot 当前只实现一个完整最小循环，同时保留项目级配置和组合根。设计权威是
[RFC 0300](docs/rfc/0300-unified-architecture-and-contracts.md)。

## 系统结构

```text
config.example/（源码模板） ──复制──→ config/（个人配置，Git 忽略）
                                      │
                         TOML + prompts/**/*.md
        │ 每个文件由同名模块注册
        ▼
AuroraConfig
        │
        ├── AgentCatalog（agents.toml 的无状态预定义原型）
        ├── Model（LiteLLM 配置构造或调用者注入）
        ├── ToolRegistry（AgentCatalog → aur.agent.delegate + 调用者注入）
        ▼
composition/{agents,ai,prompt,console,tools,engine}.py 注册构造结果
        │
        ▼
AuroraAssembly → AuroraRuntime.create_tree(message)
        │                         ┌── OpsRuntime ← OperationSpec 注册目录
        ├── AgentTree 快照 ──────→│   ├── method/path
        │                         │   └── /斜杠文本
        ▼                         └── ConfigAccess → config/（限定改动）
AgentTreeRunner ─── PromptAssembler
        ├── LiteLLMModelGateway.complete(ModelRequest)
        └── ToolRegistry.execute(ToolCall)
                ├── ToolOutput → tool message
                └── DelegationRequest → child AgentNode

aurora start
        ├── Console：普通文本 → 新 AgentTree
        ├── Console：/命令 → OpsRuntime
        └── --headless / SIGINT / SIGTERM → 共享停止事件
```

`aurora` 是项目的唯一组合根。配置合并、组件构造和最终运行入口各自只有一个权威路径。

项目层按已确定的变化轴分包：

```text
aurora/
  commands/        每个 CLI 命令独立注册与执行
  configuration/   每个 TOML 一个纯配置、解析与注册模块，目录层级与 config 对齐
  composition/     每个需实例化的 src 子包一个构造与注册模块
  utils/           子进程、TOML 字段读取等无项目语义工具
  config.py        ConfigKey、AuroraConfig 与通用配置合并器
  composer.py      InstanceKey、组合上下文与只读实例集合
  runtime.py       执行项目组件注册并提供使用门面
  main.py          只解析顶层 CLI 并分派命令

ops/
  operations/      按领域注册操作资源
  contracts.py     OperationSpec、结果与窄运行时端口
  parser.py        斜杠文本参数解析
  router.py        method/path 与文本共用路由
  config.py        个人配置读取与限定写入
  runtime.py       操作目录和端口门面

src/
  agents/          AgentDefinition 的不可变目录与唯一解析
  ai/              LiteLLM 模型网关与 OpenAI-compatible 映射
  console/         可注入分派端口的本地异步终端
  contracts/       AgentTree、四角色消息、Model 与 Tool 公共契约
  engine/          AgentTree 的确定性最小循环
  prompt/          四角色 PromptAssembler
  tools/           aur.* 工具目录、唯一执行路由与框架内建工具
  utils/           标准库日志、时间、文本与 JSON 工具
```

`config.example/` 随源码发布，`config/` 只保存用户副本且不受 Git 跟踪。运行时不会隐式读取模板。配置模块不构造 Runner；
Markdown Prompt 到 PromptCatalog 的转换只由 prompts 配置模块负责，运行实例转换发生在 composition。
增加命令、TOML 配置或项目组件时，新增对应模块并在
目录入口的注册元组增加一项；通用 Config、Composer、runtime 和 CLI main 不增加分支。

## AgentTree

一棵树就是一次运行。节点具有相同结构与循环，但每个节点显式持有四类实例差异：

- definition：创建本节点的预定义 Agent 原型 ID；
- prompt：决定本节点使用的 Agent 专属 prompt；
- model：决定本节点每次请求使用的 LLM；
- tools：决定本节点可见的 Tool 定义；
- 第一条 message：root 的外部输入或 child 的局部 assignment。

节点只保存 `message / assistant / tool` transcript；唯一 system 消息由 `PromptAssembler` 在调用模型前根据全局 system 和
prompt 生成。这样 system 的来源可配置，而已经发生的对话仍保持追加式事实。

`agents.toml` 预定义无运行状态的 `AgentDefinition`：稳定 ID、用途说明、prompt、model、tools 和允许的 child definitions。
它不是树外的活跃实例，不保存 transcript、parent 或状态。同一个 prompt 可以形成多个不同 model/tools 组合；root 由
`runtime.tree.agent` 选择，child 由 delegate 选择，并在创建时把定义事实复制到新的 AgentNode。

## 最小循环

Runner 深度优先选择最新的 ready 节点。没有待处理 Tool call 时组装 prompt 并调用节点自己的 model；assistant 无 Tool
call 时完成节点，有 Tool call 时交给唯一 `ToolRegistry` 依次执行。普通 `ToolOutput` 追加为 tool 消息；
`aur.agent.delegate` 与其他工具一样由目录路由；其原生 schema 从 AgentCatalog 列出可选 definition ID 与用途说明，调用只需
目标 Agent ID 和 instruction。它产生不持有 AgentTree 的 `DelegationRequest`，再由 Runner 校验 parent 的 child allowlist、
从目标 definition 创建 child 并暂停 parent。child 结束后，结果以对应 Tool call id 的 tool 消息恢复 parent。root 结束即
整棵树结束。

Tool ID 统一使用来源稳定的 `aur.*` 域名。框架内建 `aur.agent.delegate` 创建 child；服务工具
`aur.serv.world.read` / `aur.serv.world.trees` 由 WorldJournal 端口支撑，分别提供按 scope 有界读取提交正文（声明观察该
scope，让未披露 delta 先送达）与列出从提交推导的 Bot 森林索引。Provider adapter 为仅接受受限函数名的协议生成稳定安全
别名，并把模型响应映射回领域 Tool ID。注册表在项目组合时把框架内建工具与调用者注入工具形成一个扁平、不可变目录，
负责 ID 校验、重复拒绝、定义筛选、唯一分派与异常规范化；节点的 tools 集合只控制可见性，不复制定义或执行器。

当前循环是单线程、内存内、无恢复的。这个限制用于保持语义透明；未来并发或持久化必须产生等价 AgentTree，而不能建立
第二套运行模型。

## Ops

`runtime.ops` 是 AgentTree 热路径之外的统一监测与改动入口。同一份 `OperationSpec` 同时供
`execute(method, path, params)` 和 `route_text("/command ...")` 使用，因此未来 HTTP、Console 或 Panel 适配器不再各自定义
命令语义。当前目录覆盖操作自描述、运行状态、树与节点快照、新树启动、配置目录和配置读取。

ops 通过协议接收组合根提供的能力，不导入 `aurora` 或 `src`。Runner 的观察回调只发布新的不可变 AgentTree；
`AuroraRuntime` 保存每个 tree id 的最新快照，ops 不复制或修改树。配置改动仅限个人 `config/apps.toml` 与
`config/extensions.toml` 的既有 `enabled` 字段，使用 TOML round-trip 写回以保留注释；`config.example/` 及未注册文件不可写。
是否需要重启由操作结果中的 `restart_required` 明示。

## Console 与 start

`src.console.TerminalConsole` 只依赖 `TerminalDispatcher`，不导入 ops、engine 或 aurora。组合根把普通文本映射为新树操作，
把斜杠文本交给同一 OperationSpec 目录，再把操作结果翻译为终端文本、清屏或停止控制。EOF、`/exit`、SIGINT 和 SIGTERM
最终设置同一个停止事件。`--headless` 只禁用 Console，不建立第二条运行路径。

`models.toml` 的 endpoint 键是 AgentNode 和 ModelRequest 显式携带的模型端点 id。`composition.ai` 在没有调用者注入 Model 时构造
`LiteLLMModelGateway`；`litellm` provider 映射为 `provider/model`，`openai_compatible` provider 映射为
`openai/model + api_base`。密钥只在调用时从声明的环境变量读取。

## 包依赖

```text
utils   contracts ← agents/prompt
           ▲              ▲
           ├── ai         │
           ├── tools ─────┤
console ───┴──── engine ← aurora → ops
```

- `utils`、`contracts` 和 `console` 不依赖上层项目包；
- `contracts` 只依赖标准库；
- `agents` 和 `prompt` 只依赖 contracts，`tools` 依赖 contracts 与 agents，`ai` 只依赖 contracts 与 LiteLLM；
- `engine` 只依赖 contracts、agents、prompt 与 tools；
- `ops` 只依赖标准库和 tomlkit，与 `src` 互不导入；
- `aurora` 负责配置和具体装配。
