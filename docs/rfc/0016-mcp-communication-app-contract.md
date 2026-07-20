# RFC 0016：MCP 通信 App 契约

状态：已接受
日期：2026-07-20

## 背景

RFC 0015 将 Aurora 的 Agent 视为 Bot 自身，将 Platform 视为与外界交互的媒介，并把 MCP App 区分为普通应用与
通信应用。当前 MCP 配置只声明 package、transport、工具 allowlist 和 `result_mode`；notification 只有自由形态的
`type/session_id/data`。这足以接入 Clock 等工具，但不足以让 QQ-MCP、Discord-MCP 在同一认知基底下可靠收发、回复
和跨平台转发。

本 RFC 定义首版受控 MCP communication App。它不试图适配任意第三方消息工具 schema，而是要求通信 App 实现一组
canonical notification、publication tool 和 outcome 契约。普通 MCP App 继续只提供外部感受或影响能力，不因此
获得通信路由语义。

## 决策

### MCP Platform、App 与 endpoint

MCP 是一个 Platform，负责 stdio/Streamable HTTP 连接、App 生命周期、工具发现、notification ingress 和 effect/
publication 执行。每个 `[[app]]` 是设备上的一个显式安装应用。

App 必须声明：

```toml
kind = "utility"       # 或 "communication"
```

`utility` App 只提供普通 effect 或领域 notification，例如 Clock。`communication` App 提供一个 communication endpoint，
首版 `endpoint_id` 等于 App 的唯一 `package`，并代表一个已认证的外部 Bot account。一个 App 绑定多个 account、同一
package 建立多个 endpoint 或运行时热增删不属于本 RFC。

QQ-MCP 与 Discord-MCP 使用不同 package，可以同时注册在一个 MCP Platform 中。它们共享同一 Runtime、Kernel、
SOUL、受 audience 过滤的 Brain Context 和 Agent profiles，不创建 QQ Agent 或 Discord Agent。

### 严格 App 配置

`config/apps.toml` 中启用 App 的结构改为：

```toml
[[app]]
package = "com.example.discord"
kind = "communication"
enabled = true
transport = "stdio"
working_dir = "extensions/discord"
command = ["uv", "run", "discord_mcp.py"]
timeout_seconds = 30

[[app.tool]]
name = "com.example.discord.publish"
kind = "publication"

[[app.publication]]
capability = "com.example.discord.reply"
tool = "com.example.discord.publish"
operation = "reply"

[[app.publication]]
capability = "com.example.discord.relay"
tool = "com.example.discord.publish"
operation = "relay"

[[app.destination]]
alias = "discord.dev"
description = "Discord development channel"
capability = "com.example.discord.relay"
address_ref = "channel:configured-opaque-id"
allowed_source_audiences = ["owner.local", "com.example.qq:*"]
target_audience_ref = "com.example.discord:dev"
```

普通 App 工具声明为：

```toml
[[app.tool]]
name = "org.aurora.clock.get_current_time"
kind = "effect"
```

配置约束为：

- `app.kind` 必填，只能是 `utility` 或 `communication`。
- `app.tool.kind` 必填，只能是 `effect` 或 `publication`。
- `effect` 工具回执后总是恢复请求 Agent；`publication` raw tool 只允许 communication App 声明。
- 每个 `app.publication` 必须包含唯一 capability、同 App publication tool 和单一 operation。
- publication capability 使用完整 dotted name，可以有多个 capability 映射同一个 raw tool；profile 授权和
  CapabilityDescriptor ID 均使用 capability，不使用 raw tool name。
- operation 只能是 `reply`、`relay`、`proactive_send`；一个 capability 只能绑定一种 operation。
- communication App 必须恰好声明一个 reply capability。
- `app.destination` 只能属于 communication App；alias 全局唯一且使用 `<endpoint-short-name>.<target>` 形式。
- endpoint short name 是 package 最后一个段；alias 的首段必须与其相等。
- destination capability 必须是同 App 的 relay 或 proactive_send capability，不得是 reply。
- `allowed_source_audiences` 必填，元素是精确 audience 或仅在末尾使用 `:*` 的 endpoint conversation scope。
- `target_audience_ref` 必填，是该配置目标的稳定非秘密 audience 标识，不提供私有 address。
- `address_ref` 是非秘密 opaque 值，不提供给模型；token 仍只能来自 `auth_env`。
- 未知键、重复 package/tool/capability/alias、跨 App 绑定或非法 audience pattern 必须在启动前失败。

删除 `app.tool.result_mode`；普通 effect 固定 resume，Publication 的 Task 后续由请求的 `completion_mode` 决定。当前
仓库没有 terminal MCP 工具，因此不提供旧字段兼容。

### Canonical inbound notification

communication App 仍通过 `aurora/event` 或 MCP `notifications/message` 中的 `aurora/event` data 发送事件，但
`message.received` 必须严格符合：

```json
{
  "type": "message.received",
  "external_event_id": "stable-event-id",
  "external_message_id": "stable-message-id",
  "conversation_ref": "opaque-conversation-ref",
  "actor_ref": "opaque-actor-ref",
  "reply_route_ref": "opaque-reply-route",
  "authored_by_self": false,
  "origin_delivery_id": null,
  "summary": "New QQ message",
  "data": {
    "text": "message text"
  }
}
```

MCP adapter 必须：

1. 从当前连接覆盖 endpoint ID，不接受 notification 自报 package 或 endpoint。
2. 校验所有必填字段、非空字符串和严格 data schema；`origin_delivery_id` 只允许字符串或 null；未知顶层字段失败，
   不静默降级为用户消息。
3. 根据 `endpoint_id + external_event_id` 确定性生成 AMP message ID。
4. 根据 `endpoint_id + conversation_ref` 确定性生成 audience ref，不接受 App 自报 audience。
5. 在转交 ingress 前要求受信任 App 已持久化 reply route；route 只能绑定同 App 的 reply capability。
6. 对每一个事件都使用 `endpoint_id + external_message_id` 查询 MCPPlatform 本地 dispatch ledger；匹配成功时形成
   delivery update，不创建普通 Task。若同时提供 origin delivery ID，它必须与账本匹配。
7. 将文本和规范化 CommunicationContext 写入 AMP，保留 source app=package、source instance=MCP connection identity。

受信任 App 必须根据其已认证 account 正确填写 `authored_by_self`。该值只是 connector 提示，不能跳过或替代
MCPPlatform ledger 检查：即使值为 false，匹配本地 outbound external message ID 的事件仍是 delivery update；值为
true 但没有匹配账本的事件表示 Aurora 外部发送或账本不完整，进入隔离审计，不得作为普通外部用户输入，也不得被
自动丢弃。App 已知 delivery ID 时必须填写 origin delivery ID；不知道时为 null，仍可按 external message ID 匹配。

非通信领域 notification 可以继续使用 RFC 0014 的自由 `type/session_id/data` 归一化，但不得伪装成
`message.received`，也不得携带 reply route。

### Canonical publication tool

communication App 的 publication 工具必须接受以下固定 input schema；工具名仍使用 `<package>.<tool>`：

```json
{
  "operation": "reply",
  "route_ref": "opaque-route-or-null",
  "address_ref": "opaque-address-or-null",
  "text": "non-empty text",
  "delivery_id": "publication-request-id",
  "provenance": {
    "source_endpoint_id": "com.example.qq",
    "source_external_event_id": "event-id",
    "source_audience_ref": "com.example.qq:conversation-hash",
    "destination_endpoint_id": "com.example.discord",
    "target_audience_ref": "com.example.discord:dev",
    "hop_count": 1
  }
}
```

约束为：

- `reply` 必须只有 route_ref；App 必须确认 route 属于自身 endpoint。
- `relay` 与 `proactive_send` 必须只有 address_ref；MCP adapter 只从已验证 DestinationGrant 注入该值。
- 模型只能提供 destination alias、text、completion mode 和 proactive reason；operation 由 capability 固定，route、
  address、delivery ID 与
  provenance 均由运行时注入。
- delivery ID 是幂等键。同一 delivery ID 和相同请求必须返回同一结果；同 ID 不同请求必须失败。
- provenance 用于审计和防环，不得由 App 改写或解释为外部用户身份。

工具成功结果必须严格为：

```json
{
  "status": "accepted",
  "delivery_id": "publication-request-id",
  "external_message_id": "platform-message-id"
}
```

明确拒绝使用 MCP tool error 或 `isError`，形成 `publication.failed`。连接在 dispatch-start 后中断、超时或返回无法验证
的结果形成 `publication.delivery_unknown`，不得作为普通 failed 自动重试。App 支持按 delivery ID 查询时可以提供独立
utility effect 工具供 root 或维护流程 reconciliation，但本 RFC 不定义自动重试。

### 模型工具投影

原始 canonical publication schema 不直接暴露给模型。Kernel 根据 profile、启动 catalog、当前 Task grant 和 audience
policy 生成有效 descriptor 投影，ToolAgent 只把该只读投影转换成 endpoint 工具：

```json
{
  "destination": "configured-alias",
  "text": "message text",
  "complete_task": true,
  "reason": "required for proactive_send"
}
```

投影规则为：

- 每个模型工具对应一个 publication capability 和固定 operation；模型不能切换 operation。
- 当前 Task 有该 endpoint 的 ReplyRoute 时才提供 reply capability，并隐藏 destination。
- relay/proactive 只列出 profile 授权、App 活动、source audience 允许的 destination alias。
- 一个来源 App 不屏蔽其他通信 App；QQ Task 可以看到获授权的 Discord destination。
- 子 Agent 看不到任何 publication 工具，即使 profile 声明了对应 capability。
- 没有任何有效 operation 或 destination 时，不向模型提供该 publication capability。

这里的 App 活动只表示启动时已启用并成功加入不可变 catalog。瞬时连接断开不改变工具投影，调用时形成 failed 或
delivery_unknown。Kernel 在提交 PublicationRequest 时重新授权，ToolAgent 不查询 Kernel、MCPPlatform 或配置。

ToolAgent 把 `complete_task = false` 映射为 `completion_mode = continue`，把 `true` 映射为
`complete_on_success`；该控制字段不发送给 MCP App。

### Platform 私有路由与账本

每个受信任 communication App 是自身外部 account、conversation 和 reply route 完整性的权威，必须在 App 私有存储
中持久化：

- reply route ref 到 App 私有 conversation/reply 参数的映射及 TTL；
- App 判断 authenticated account 是否为消息作者所需的私有账号信息。

本地 App 可以使用 `AURORA_APP_DATA_DIR`，远程 App 必须使用其服务端持久化；route 在 MCP 重连后保持有效直至到期。
Aurora 将显式启用的 communication App 视为可信 connector：若 App 把错误 conversation 绑定到 route，等同于
Platform 错误投递，不由 Kernel 二次证明。route ref 在 endpoint 内唯一，绑定 account、conversation、reply raw tool
和 TTL；同一 external event 重放必须返回同一 route。

MCPPlatform 另在 `data/platform/mcp/publications.sqlite3` 保存不含 route 私有地址的本地 dispatch ledger：

- publication request ID、endpoint、capability、raw tool 和规范请求摘要；
- dispatch-start 与 accepted/failed 终态；
- accepted 的 `delivery_id -> external_message_id` 关联；该索引用于核对所有 inbound communication event。

Kernel 只保存 RFC 0015 的 grant 元数据、Publication Activity、outcome 和因果事实。App route 先落盘、AMP 后 ingress；
若 ingress 失败，孤立 route 按 TTL 清理。Kernel Task 已创建但 App route 丢失时，reply 形成明确 failed，不得猜测
conversation。认证 token 不得写入 App route、MCPPlatform ledger 或 Kernel。

### 配置安装与重启恢复

配置解析生成两份来自同一 configuration hash 的不可变视图：

- Kernel/public view：alias、endpoint、publication capability、单一 operation、source audience policy 和
  target audience；
- MCPPlatform/private view：上述 binding 加 raw tool 与 address ref。

`aurora` 组合层分别把 public view 注入 KernelConfiguration、把 private view 注入 MCPPlatform。Platform 不查询或安装
Kernel grant，Kernel 不取得 address ref。Kernel 授权后，Publication lease 只携带 endpoint、capability 和 alias；
MCPPlatform 用自己的同 hash 快照验证并解析 raw tool/address。hash 不一致时启动失败。

重启时 Kernel 不把 PROCESSING Publication 直接转换为普通 effect failure。localhost 从 Kernel 领取恢复项，并通过
MCPPlatform recovery port 按 request ID 查询本地 dispatch ledger：无记录返回 interrupted_before_dispatch；有终态返回
同一 accepted/failed outcome；有 dispatch-start 无终态返回 delivery_unknown。MCPPlatform 不读取 Kernel，localhost
不读取 ledger 数据库。恢复 outcome 使用确定性 AMP message ID，重复启动不重复恢复 mailbox。

## 与既有 RFC 的关系

本 RFC 在接受后：

- 扩展 RFC 0004 的 MCP App 与完整工具名契约，增加 utility/communication App、effect/publication tool 和
  destination allowlist；保留显式启用、package namespace、stdio 与 HTTPS Streamable HTTP。
- 部分取代 RFC 0014 的自由 MCP notification 规则；普通领域 notification 继续有效，通信 message 使用本 RFC 的
  canonical schema。
- 取代 `app.tool.result_mode` 配置；普通 effect 固定恢复，通信工具遵循 RFC 0015 Publication。
- 保留 RFC 0014 的单 MCP Platform、统一 ingress、唯一 executor、单 Runtime 和禁用 App 无副作用。

## 非目标

- 自动适配任意第三方 MCP 消息工具 schema；不兼容的 Server 需要一个符合本 RFC 的 adapter App。
- 同 App 多账号、多 endpoint、短工具名重写、动态 capability catalog 和运行中热插拔。
- 任意联系人发现、自然语言地址解析、临时 destination grant 和跨 tenant 通信。
- 附件、reaction、编辑、删除、typing、presence 或富媒体转换。
- 自动双向桥接、跨 Platform 历史同步和自动重试 unknown delivery。

## 验收标准

1. Clock 以 utility App/effect 工具运行，行为与现有 resume 闭环一致，配置不再包含 result_mode。
2. 两个不同 package 的 communication App 可同时注册 endpoint、reply route、publication capability 和 destination。
3. 相同 external event ID 的 MCP 用户消息重放只形成一个 AMP 和一个 Task。
4. malformed communication notification、跨 App reply route、自报 endpoint 和无稳定 ID 的用户消息确定性拒绝。
5. QQ 消息创建的 root 能看到获授权 Discord alias，执行 relay 后由 outcome 恢复，再通过原 QQ route 回复并完成 Task。
6. 模型、continuation 和 Brain Context 不包含 route 私有地址、destination address_ref、token 或 delivery ledger 私有字段。
7. 子 Agent 和未获 source audience 授权的 root 都看不到 publication target。
8. accepted、failed 和 delivery_unknown 分别形成正确 Publication outcome；unknown 不自动重试。
9. 同一 delivery ID 重放不重复发送，不同请求复用同 ID 确定性失败。
10. inbound external message ID 与本地 delivery ledger 匹配时，无论 self-authored 提示为何都成为 delivery update；
    无账本的 self-authored 消息进入隔离审计，二者都不创建普通用户 Task。
11. 禁用 communication App 不启动连接、不注册 endpoint/grant resolver/capability，也不创建 App 数据文件。
12. MCP Platform 不直接修改 Kernel，localhost 不解析 QQ/Discord 私有地址，依赖方向继续符合 RFC 0014。
