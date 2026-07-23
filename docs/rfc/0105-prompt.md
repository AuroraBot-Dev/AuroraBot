# 0105：提示词装配

状态：已接受
日期：2026-07-23
来源：取代 RFC 0019

## 职责

`src/prompt/` 是项目自有模型提示词的唯一加载、分层 DTO 和装配边界。
只依赖 `src/contracts` 和标准库；不调用 Kernel、Provider 或 Platform。

## 提示词清单

`config/prompts.toml` 声明提示词结构：

```toml
[system]
soul = "prompts/SOUL.md"
world = "prompts/WORLD.md"

[agent]
"builtin.gate" = "prompts/agents/gate.md"
"builtin.worker" = "prompts/agents/worker.md"
```

所有引用文件必须是互不复用、存在且 UTF-8 的 Markdown 文件。
SOUL 可以为空；world 与 Agent profile 不得为空。

## 核心组件

### PromptCatalog

启动时加载的不可变提示词目录。记录 SOUL、world 和每个启用 Agent profile 的 Markdown 正文及哈希。

### PromptDocument 与 PromptSection

分层装配 DTO。一次模型 turn 形成一个 `PromptDocument`：

```text
system_sections = soul, world, agent_profile
user_sections   = source, message, current_work, situations, available_tools
```

每个 section 有稳定 key 和正文。内部保留分层，最终 Provider 输入为
一个 system message 和一个 user message（按顺序拼接非空 section）。

### PromptComposer

根据 `AgentContext` 生成 system/user 文档。ToolAgent 必须安装 PromptComposer 后才能请求模型。
不存在 composer-less JSON fallback。

## 命名与风格规则

- SOUL 只描述人格
- world 使用与 SOUL 相容的自然语言描述世界运转方式
- Agent profile 描述当前角色
- 不得在默认片段中把主体称为 AI
- 沟通边界应作为世界事实表达（如"写好但没有寄出的信不会被收到"）

## 不属于提示词资产的内容

- 用户、Platform、MCP Server 或 Tool 返回的外部原始文本
- 领域结果字段、错误码和运行时诊断
- Tool 名称、描述、schema 等提供方契约

PromptComposer 决定这些事实如何进入模型上下文，但不得静默改写或搬成项目自有提示词。

## Tool 描述归属

Tool 名称、描述和参数 schema 由各自提供方管理：

- Console、Dashboard Tool 定义在 Platform adapter 实现域
- Clock MCP Tool 在 Clock Server 的 `tools/list` 中定义
- 第三方 MCP Tool 的 `tools/list` 结果原样进入 capability catalog
- `src/prompt/` 不维护 Tool 描述覆盖表，不改写任何 Tool 描述

## 无隐式回复

纯文本 completion 保持 Agent completion。若没有调用 send Tool，外界不会收到文字。
不存在把模型纯文本自动改写成 Console/Dashboard Tool 调用的兜底逻辑。

## 约束

- `AgentProfile`、`KernelConfiguration` 和 `BrainContextSnapshot` 不保存提示词正文
- Kernel 数据库不保存 SOUL、world 或 Agent 指令
