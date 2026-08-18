# AuroraBot

AuroraBot 当前是以 `AgentTree` 为核心的自主智能体实验框架。仓库处于架构收核阶段，不是待发布产品；只保留完整最小循环
和项目级组合骨架。

## Architecture authority

- `docs/rfc/0300-unified-architecture-and-contracts.md` 是唯一设计基准。
- `docs/` 是独立文档仓库的子模块；RFC 先在 docs 仓库提交，再由主仓库更新子模块指针。
- 影响 AgentTree、四角色消息、模型/工具端口、配置或组合根的改动，必须先更新 RFC。
- Python 源码和测试的注释与 docstring 不提具体 RFC 编号，直接说明局部不变量。

## Project layout

```text
config/         最小项目组合配置；apps.toml 仅作为尚未迁移的用户配置保留
aurora/         项目级入口；commands / configuration / composition 分包与 runtime 门面
src/contracts/  AgentTree、ChatMessage、Model 和 Tool 公共契约
src/prompt/     四角色 PromptAssembler
src/engine/     AgentTree 的确定性单循环
src/ai/         Provider 协议边界的纯适配函数
tests/          离线行为、组合与边界测试
docs/           文档站点与唯一 RFC 子模块
panel/          暂不参与当前 runtime 的独立前端子模块
```

## Core boundaries

- 一棵 `AgentTree` 表示一次完整运行；不再引入独立 Task、mailbox、Activity 或 continuation 作为平行运行模型。
- root 与 child 使用同一种 `AgentNode` 和循环。实例只因 system profile、初始 message、可见 tools 和 LLM model 不同。
- `ChatMessage` 只允许 `system`、`message`、`assistant`、`tool` 四种领域 role；只有 Provider adapter 可把
  `message` 映射成协议的 `user`。
- `PromptAssembler` 只装配上下文，不访问模型、工具、数据库或记忆服务。
- `AgentTreeRunner` 只依赖 contracts + prompt；普通 Tool 经端口执行，`delegate` 是唯一由 engine 解释的内建 Tool。
- model id 是节点事实，必须显式进入每个 `ModelRequest`，不得由全局 runner 或 profile 隐式推导。
- `aurora` 是唯一项目组合层：`configuration` 只产生纯 DTO，`composition` 分阶段构造 Prompt、Engine 与 Runtime，
  `commands` 按模块注册 CLI，`main.py` 只分派。
- 依赖方向固定为 `contracts ← prompt/ai ← engine ← aurora`；`src` 不导入 `aurora`。

## Current exclusions

当前不实现持久化、迁移、自动记忆、Inbox/Triage、并发/抢占、MCP、Platform、ops、Panel backend、sandbox、费用或生产化
生命周期。重新加入任何一项前，先给出围绕 AgentTree 的真实用例、不变量和独立测试，不恢复旧兼容层。

## Language and text

- 项目文本以简体中文为默认和权威版本，包括 CLI 帮助与输出、错误说明、配置注释、默认 Prompt、README 和设计文档。
- 代码标识符、协议字面量、外部 API 字段和必要的技术术语可以使用英文；面向人的完整句子优先使用中文。
- 英文与日文翻译可以保留，但中文内容先更新；翻译冲突或落后时以中文为准。

## Runtime and quality

- Python 3.12，使用 uv。
- Ruff 行宽 120，LF，双引号；公开 API 有类型注解；值对象优先 frozen + slots dataclass。
- 主源码文件不超过 500 行；不以 lint ignore 掩盖核心复杂度。
- 测试必须离线、确定、无数据库、无网络、无环境变量依赖；Model 和 Tool 使用 fake。
- 提交前运行 `uv run aurora check`。
