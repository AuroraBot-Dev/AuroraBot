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
        ├── Model / Tools（由调用者注入）
        ▼
composition/{prompt,engine}.py 注册构造结果
        │
        ▼
AuroraAssembly → AuroraRuntime.create_tree(message)
        │
        ▼
AgentTreeRunner ─── PromptAssembler
        │
        ├── Model.complete(ModelRequest)
        ├── Tool.execute(ToolCall)
        └── delegate → child AgentNode
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
```

`config.example/` 随源码发布，`config/` 只保存用户副本且不受 Git 跟踪。运行时不会隐式读取模板。配置模块不构造 Runner；
Markdown Prompt 到 PromptCatalog 的转换只由 prompts 配置模块负责，运行实例转换发生在 composition。
增加命令、TOML 配置或项目组件时，新增对应模块并在
目录入口的注册元组增加一项；通用 Config、Composer、runtime 和 CLI main 不增加分支。

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
