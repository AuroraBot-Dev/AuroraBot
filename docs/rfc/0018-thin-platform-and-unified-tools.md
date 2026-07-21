# RFC 0018：薄 Platform 与统一 Tool 运行时

状态：已接受
日期：2026-07-21

## 背景

RFC 0015、0016 为了解决一次 terminal effect 结束整个 Task、跨平台回复和投递恢复问题，引入了
`utility/communication` App、`effect/publication` capability、`reply/relay/proactive_send` operation、ReplyRoute、
DestinationGrant 和 canonical communication notification。实现证明了多次工具续跑、三态结果和可靠恢复是有价值的，
但分类式契约让 Platform 替 Agent 作出了过多认知决定，并要求第三方 MCP Server 遵循 Aurora 私有配置与消息惯例。

Aurora 的认知核心是 LLM Agent。Platform 的职责是把外部事实和工具带入同一个运行时，并执行 Agent 已选择的工具，
而不是预先判断某个 App 是否属于通信、某个工具是否属于发布、一次调用是回复、转发还是主动发送。Console、
Dashboard、Clock、QQ 和 Discord 对 Agent 都应表现为来源不同但地位相同的工具与事实。

MCP 是开放扩展边界。一个符合标准 MCP tools/list 与 tools/call 的第三方 Server 必须能够直接接入；不得要求它修改
工具名、参数 schema、结果 schema、notification 字段或补充 Aurora 专用 manifest 才能被 Agent 使用。

## 目标

1. 所有外部能力使用同一种 Tool 契约、Activity 和结果闭环。
2. Console、Dashboard 与任意 MCP Server 的工具进入同一个扁平 capability catalog。
3. Agent 获得当前事实、Brain Context 和全部获授权活动工具，自行决定调用哪个工具及调用顺序。
4. 第三方 MCP Server 只需标准 MCP 协议和最小连接配置即可拿来即用。
5. 多次工具调用、Task 完成控制、幂等与重启恢复继续可用，但不以 App/工具语义分类为前提。

## 决策

### Platform 是薄适配层

Platform 只拥有以下职责：

- 管理自身协议、连接、生命周期和私有资源；
- 把外部事件归一化为 AMP，保留来源、session、summary 和原始规范化 data；
- 注册当前实际可用的 Tool descriptor 与唯一 executor；
- 执行一次已授权 Tool request，并返回结构化 outcome；
- 可以实现幂等账本、恢复、防回流、缓存或目标解析，但这些是适配器能力，不是 Agent/Kernel 强制分类。

Platform 不得：

- 把 App 归类为 utility、communication 或其他认知类别；
- 把 Tool 归类为 effect、publication、reply、relay 或 proactive；
- 根据输入来源替 Agent 隐藏其他活动 Tool；
- 规定 Agent 应在哪个平台回复；
- 要求第三方 MCP Server 实现 Aurora 私有 Tool 或 notification schema。

Console、Dashboard 和 MCP 仍是并行 Platform。MCP Platform 可以承载任意数量的外部 App；App 是连接与命名空间，
不是认知主体或能力类别。

### 统一 Tool descriptor

活动 capability catalog 只包含统一 `ToolDescriptor`：

```text
id
description
parameters_schema
```

`id` 是 Aurora 运行时中的全局名称。内建 Platform 使用稳定 package 前缀：

```text
org.aurora.console.<tool>
org.aurora.dashboard.<tool>
```

MCP App 配置提供唯一 package；Server 返回的每个原始工具名 `raw_name` 被映射为：

```text
<configured-package>.<raw_name>
```

映射只发生在 MCP adapter 内部。调用时 adapter 使用原始 `raw_name`，第三方 Server 无需知道 Aurora package，也无需
修改其工具名。两个 Server 都暴露 `send_message` 时会分别形成 `com.tencent.qq.send_message` 和
`com.discord.send_message`，不会冲突。

ToolDescriptor 不包含 App kind、Tool kind、operation、endpoint、root-only、result mode 或 destination grant。

### 最小 MCP 配置与动态发现

`config/apps.toml` 中一个 MCP App 只声明连接与生命周期：

```toml
[[app]]
package = "com.tencent.qq"
enabled = true
transport = "stdio"
working_dir = "extensions/qq"
command = ["qq-mcp"]
timeout_seconds = 30
```

Streamable HTTP App 可以声明 `url` 和 `auth_env`。不存在以下结构：

- `app.kind`；
- `app.tool` allowlist；
- `app.publication`；
- `app.destination`；
- Aurora 专用工具参数映射。

MCPPlatform 在启动时使用标准 `tools/list` 动态发现全部工具。发现结果直接形成 ToolDescriptor。安装或配置 App 仍不
等于启用；只有 `enabled = true` 且成功连接的 App 才进入活动 catalog。不同 App 映射后的 Tool ID 必须唯一。

Server 工具在运行期变化、MCP resources/prompts 和 App 热插拔由后续 RFC 决定；首版 catalog 仍是启动快照。

### Agent 的工具自由

Kernel 根据 Agent profile 的能力策略与活动 catalog 生成每 turn 的工具视图，但不按 Platform、来源或工具语义过滤。
profile capability 支持：

- 精确 Tool ID；
- package 末尾通配，例如 `com.tencent.qq.*`；
- `*` 表示全部活动 Tool。

内建 root 与 worker profile 默认使用 `*`。能力策略是部署者可选的安全收窄，不是 Platform 强制语义；子 Agent 与根
Agent 使用同一授权算法，不存在只因工具可能向外输出而自动 root-only 的规则。

ToolAgent 将所有有效 ToolDescriptor 原样提供给模型。模型从 AMP source、session、data、Brain Context、工具说明和
JSON Schema 自己判断：

- 是否需要回应；
- 使用来源平台还是另一个平台；
- 调用一个还是多个工具；
- 是否委派子 Agent；
- 何时结束当前工作。

Kernel 和 Platform 不推断 reply、relay、proactive 等意图。

### 单一 Tool 决策与 Activity

`AgentDecision` 使用一个 `tool_request`，取代 `effect_request` 和 `publication_request`。ToolRequest 包含：

```text
capability
parameters
complete_task
tool_call_id
continuation
```

`complete_task` 是 Agent 对控制流的声明，不是第三方 Tool 惯例。仅当原始 schema 未定义同名属性时，ToolAgent 才向
模型展示的 schema 增加可选保留布尔字段 `complete_task`，默认 `false`；从模型 Tool Call 转换为 ToolRequest 时移除
该保留字段，Platform 和 MCP Server 只收到原始工具参数。

如果原始 schema 已定义 `complete_task`，该属性属于第三方 Tool：schema 和调用参数都必须原样提供给模型与 executor，
不得作为 Runtime 控制字段剥离。本次 ToolRequest 的控制值默认为 `false`，Agent 可以在收到结果后的后续 turn 显式完成
工作。支持保留控制字段是 Aurora 的可选增强，不构成第三方 Tool 的命名或 schema 惯例。

Tool request 创建 `kind = tool` 的持久化 Activity。每个 Agent 仍保持一轮一个主要动作和最多一个活跃 Activity；不同
Agent 可以并行。Provider parallel tool calls 继续关闭，多工具行为通过结果恢复后的下一轮决策自然涌现。

### Tool outcome 与 Task 控制

统一 ToolOutcome 有三种状态：

- `succeeded`：executor 明确完成；
- `failed`：executor 明确拒绝或失败；
- `unknown`：调用可能已经发生，但结果无法确定。

localhost dispatcher 通过内部窄完成端口把 outcome 提交给 Kernel；Kernel 再生成 `tool.succeeded`、`tool.failed` 或
`tool.unknown` 持久化邮箱事件。外部 AMP ingress 不接受这三个 Runtime 保留类型，MCP notification 也不得伪造 Tool
outcome。每个 outcome 都恢复原 Agent，但
`complete_task = true` 且 outcome 为 succeeded 时例外：

- 根 Agent：完成根 Agent 与 Task，并取消监督树剩余工作；
- 子 Agent：完成该子 Agent，并以普通 child completion 回报父级，不结束根 Task。

failed 和 unknown 永远恢复请求 Agent，不得自动重试。没有 continuation 时，receipt 作为新事实触发普通模型 turn；有
continuation 时，ToolAgent 把 outcome 附加到 Provider continuation。

因此同一个根 Agent 可以：

```text
调用 org.aurora.console.send（complete_task=false）
→ 成功回执恢复
→ 调用 com.discord.send_message（complete_task=false）
→ 成功回执恢复
→ 调用 com.tencent.qq.send_message（complete_task=true）
→ 成功后完成 Task
```

调用顺序和平台选择完全由 Agent 决定。

### 输入事实不强制通信 schema

AMP 继续是 Platform 到 Kernel 的统一事实信封。Kernel 只要求 RFC 0003 的通用字段，不要求
`CommunicationContext`、audience、actor、conversation、ReplyRoute 或 external message ID 组合。

Console 和 Dashboard 可以在 `payload.data` 中提供其认为有助于 Agent 判断的来源信息。MCP notification adapter 保留
Server 给出的 event type、session、summary 和 data，并覆盖可信的 `source.app = configured package`；不得要求事件
符合 canonical message schema。

入口继续按 AMP message ID 去重。Platform 可以根据外部 event ID 生成稳定 AMP ID；没有稳定外部 ID 时可以生成新
UUID。自发消息回流识别是 Platform 可选能力，不是 MCP App 被启用的前置条件。

### Console 与 Dashboard

Console 和 Dashboard 是内建 Tool provider，与 MCP Tool 使用相同 ToolDescriptor、ToolRequest、ToolOutcome 和
dispatcher。

两者都是单租户固定目标，因此其 send 工具不需要模型选择私有地址或 Kernel ReplyRoute：

- `org.aurora.console.send` 把文本写入当前本地 Console；
- `org.aurora.dashboard.send` 把文本持久化并推送给配置的 Dashboard owner。

模型可以从任意来源调用任一已启用工具。Console 输入触发的 Task 可以向 Dashboard 发消息，QQ 输入触发的 Task 也
可以调用 Console 或 Discord Tool。禁用 Platform 时对应 Tool 不进入 catalog。

Dashboard owner 鉴权仍是 Platform 私有安全边界；非 owner 不得伪造本地 owner 输入。该限制保护外部身份，不决定
Agent 应调用哪个工具。

### 可选执行增强

Platform executor 可以透明实现：

- request ID 幂等；
- dispatch ledger；
- PROCESSING Tool 重启恢复；
- self-loop suppression；
- 速率限制；
- 私有目标 alias；
- 更严格的结果校验。

这些增强不得改变 ToolDescriptor 的通用形态，不得成为第三方 MCP 工具进入 catalog 的必要条件。未实现恢复的
executor 遇到重启中的 PROCESSING Tool 时返回 unknown；未实现幂等的 executor 不得被 Runtime 自动重放。

### Brain Context

Aurora 是单租户人格，默认 Brain Context 恢复 RFC 0012 的全局活动投影，不因 Platform 或 session 强制隔离。Platform
来源、session 和 data 保留在 Task 事实中，供 Agent 自己判断。

部署者未来可以配置隐私投影策略，但它必须是显式、可选且与 Tool 分类无关的安全策略。本 RFC 删除强制 audience
类型及其对工具可见性的影响。

## 与既有 RFC 的关系

本 RFC 接受后：

- 完全取代 RFC 0015 的 PublicationRequest、Publication Activity、ReplyRoute、DestinationGrant、operation、
  root-only publication 和强制 audience 模型；RFC 0015 状态改为已取代。
- 完全取代 RFC 0016 的 utility/communication App、effect/publication Tool、canonical communication notification、
  publication/destination 配置和 MCP communication ledger 前置要求；RFC 0016 状态改为已取代。
- 部分取代 RFC 0012 的“只有根 Agent 可以请求 terminal 效果”；不存在 terminal 或 publication 效果。保留同构 Agent、
  监督树、邮箱、单 Activity、共享预算和根 Task 取消树。
- 扩展 RFC 0014 的活动 catalog：Console、Dashboard 与 MCP 都注册统一 Tool binding；保留 Platform 唯一执行权、
  localhost dispatcher、单 Runtime 和精确平台组合。
- 保留 RFC 0003 的 AMP、因果和外部入口去重原则；Tool outcome 改由 localhost 内部窄端口提交，不经过外部 AMP ingress。
- 部分取代 RFC 0004 的 MCP 完整工具名要求：第三方 raw tool name 无需 package 前缀，MCP adapter 在 Aurora 内部添加
  配置 package 前缀。

## 非目标

- 不让 Kernel 理解任何第三方 Tool 的业务语义。
- 不保证 LLM 每次都选择人类预期的平台或参数；这是 Agent 能力与提示词质量问题。
- 不提供默认跨平台 ACL、目标 allowlist 或通信类别。
- 不启用 Provider parallel tool calls或一个 turn 提交多个 ToolRequest。
- 不定义 MCP resources/prompts、动态 tools/list 更新或 Server 热插拔。
- 不要求所有 executor 实现幂等、恢复和自发消息回流识别。

## 验收标准

1. CapabilityDescriptor 不再包含 kind、operation、endpoint、root-only 或 result mode。
2. AgentDecision 只有统一 ToolRequest；Activity 只有 model/tool；不存在 effect/publication 双路径。
3. 任意 Agent 可以调用其 profile 策略允许的任意活动 Tool，来源 Platform 不参与过滤。
4. 原始 schema 未占用 `complete_task` 时，模型 Tool schema 获得同名 Runtime 保留字段且该字段不传给 executor；原始
   schema 已占用时，schema 与参数原样传递且本次 Runtime 控制值为 `false`。
5. Tool succeeded 根据请求控制根 Task 或子 Agent 完成；failed/unknown 恢复请求 Agent。
6. Console、Dashboard、Clock 和两个任意 MCP Server 的工具位于同一 catalog，并使用同一 dispatcher。
7. Console 输入触发的 Agent 可以选择 Dashboard Tool；QQ 输入触发的 Agent 可以依次选择 Discord 与 QQ Tool。
8. 未声明任何 Aurora Tool 配置的第三方 MCP Server，其 tools/list 结果可以直接发现、命名和调用。
9. 两个 Server 的同名 raw tool 通过配置 package 前缀形成不同 Aurora Tool ID。
10. `apps.toml` 不包含 App/Tool kind、tool allowlist、publication 或 destination 配置。
11. MCP 自由 notification 可以进入 AMP，不要求 canonical communication schema；source package 由 adapter 覆盖。
12. 禁用 Platform/App 不注册 Tool、不创建连接或私有资源；现有单向依赖边界继续通过。
13. 外部 AMP 或 MCP notification 不能伪造 `tool.succeeded`、`tool.failed` 或 `tool.unknown` 来完成 Activity。
