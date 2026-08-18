# AuroraBot 架构实施说明

AuroraBot 当前只实现一个完整最小循环，同时保留项目级配置和组合根。设计权威是
[RFC 0300](docs/rfc/0300-unified-architecture-and-contracts.md)。

## 系统结构

```text
config/aurora.toml
        │
        ▼
aurora.configuration.load_configuration
        │
        ▼
aurora.composition.assemble_runtime ─── Model / Tools（由调用者注入）
        │
        ▼
AuroraRuntime.create_tree(message)
        │
        ▼
AgentTreeRunner ─── PromptAssembler
        │
        ├── Model.complete(ModelRequest)
        ├── Tool.execute(ToolCall)
        └── delegate → child AgentNode
```

`aurora` 仍是项目的唯一组合根。收核删除的是旧组合中的生产化设施，不是“项目如何构造一套运行时”这件事本身。

项目层按已确定的变化轴分包：

```text
aurora/
  commands/        每个 CLI 命令独立注册与执行
  configuration/   纯配置 DTO 与 TOML loader
  composition/     prompt → engine → runtime 分阶段构造
  runtime.py       组合完成后的使用门面
  main.py          只解析顶层 CLI 并分派命令
```

配置 loader 不构造 PromptCatalog 或 Runner；这些转换只发生在 composition。增加命令、配置节或组合阶段时新增对应模块，
而不是扩张 `main.py` 或一个全能 assembly 函数。

## AgentTree

一棵树就是一次运行。节点具有相同结构与循环，但每个节点显式持有四类实例差异：

- profile：决定本节点的 system prompt；
- model：决定本节点每次请求使用的 LLM；
- tools：决定本节点可见的 Tool 定义；
- 第一条 message：root 的外部输入或 child 的局部 assignment。

节点只保存 `message / assistant / tool` transcript；唯一 system 消息由 `PromptAssembler` 在调用模型前根据全局 system 和
profile 生成。这样 system 的来源可配置，而已经发生的对话仍保持追加式事实。

## 最小循环

Runner 深度优先选择最新的 ready 节点。没有待处理 Tool call 时组装 prompt 并调用节点自己的 model；assistant 无 Tool
call 时完成节点，有 Tool call 时依次执行。普通工具结果追加为 tool 消息；delegate 创建 child 并暂停 parent。child 结束后，
结果以对应 delegate call id 的 tool 消息恢复 parent。root 结束即整棵树结束。

当前循环是单线程、内存内、无恢复的。这个限制用于保持语义透明；未来并发或持久化必须产生等价 AgentTree，而不能建立
第二套运行模型。

## 包依赖

```text
contracts ← prompt
    ▲         ▲
    ├── ai    │
    └──── engine ← aurora
```

- `contracts` 只依赖标准库；
- `prompt` 和 `ai` 只依赖 contracts；
- `engine` 只依赖 contracts 与 prompt；
- `aurora` 负责配置和具体装配。
