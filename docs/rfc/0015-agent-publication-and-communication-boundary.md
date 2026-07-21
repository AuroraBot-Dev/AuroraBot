# RFC 0015：Agent 发布与通信边界

状态：已取代（由 RFC 0018 取代）
日期：2026-07-20

## 背景

RFC 0012 用同构 Agent、持久化邮箱和监督树实现 AuroraBot 的认知运行时，RFC 0014 将 Console、Dashboard 和
MCP 定义为并行 Platform。当前 `terminal` effect 同时承担 root-only 授权、平台发布、成功后不恢复 Agent 和结束
Task 四种语义，导致根 Agent 只能发布一次 Console 或 Dashboard 消息，不能先发送中间消息再继续工作。

AuroraBot 的核心 Agent 机制代表 Bot 自身这个“人”。根 Agent 与子 Agent 是同一人格和 Task 监督关系中的认知
工作单元，不是不同平台上的 Bot 分身。Platform 是这个人与外界交互的媒介：MCP Platform 类似一台设备，MCP App
类似设备上的时钟、QQ 或 Discord 应用；Console 和 Dashboard 是收件人固定的专用通信 Platform。

发布权限、通信地址和 Task 生命周期必须彼此独立。一个人可以保持串行的认知 turn，同时让已经发起的模型、工具、
子任务或外部投递并行等待；主体一致性应由根 Agent 的公共表达权保证，而不是由“第一次发送即结束 Task”保证。

## 目标

1. 一个根 Task 可以按因果顺序发布零到多条消息，并明确选择继续或在投递成功后结束。
2. 只有根 Agent 能代表 Aurora 对外发布；子 Agent 继续作为同一人格下的有界认知工作单元。
3. 区分普通工具效果、通信发布和 Task 完成，不启用 Provider parallel tool calls。
4. 为来源回复和跨平台发送建立受保护的 route/destination grant，不再复用通用 `session_id`。
5. 保留单 turn、单 Activity、Platform 唯一效果执行权、持久化回执和根 Task 取消监督树等稳定边界。

## 决策

### 人、认知工作与外部媒介

一个 Aurora 部署拥有一个 tenant 和一个人格基底。每个外部根 AMP 仍创建独立 Task 和根 Agent；Task 是一次事件的
认知处理流程，不是人格、Platform 或长期 conversation。不同 Task 可以并行等待，但不得为 Console、Dashboard、
QQ、Discord 等媒介创建平台专属 Agent 类型。

同构子 Agent 是根 Agent 委派出的内部认知工作单元。子 Agent 可以并行研究、调用获授权的普通效果并回报父级，
但不能直接代表 Aurora 向任何外部媒介发言。根 Agent 独占 Publication 的采纳与提交权。

三类外部对象必须分开：

- `Platform`：拥有协议、生命周期和效果执行的外部媒介；当前为 Console、Dashboard 和 MCP。
- `Application`：运行在 Platform 上并提供感受或行动能力的应用；MCP Clock、QQ、Discord 都是 MCP App。
- `CommunicationEndpoint`：一个通信应用或专用 Platform 的可收发边界；它可以包含多个外部 conversation。

Console 和 Dashboard 分别提供固定的 `console.local` 与 `dashboard.local` endpoint。它们对 Aurora 都只有一个确定
收件目标；平台内部 UI 连接、认证记录或消息存储不得变成模型需要选择的收件地址。MCP App 是否形成通信 endpoint
及其消息契约由 RFC 0016 定义；Clock 等非通信 App 不形成 endpoint。

### CommunicationContext 与 audience

通信类根 AMP 必须在 `payload.data.communication` 中携带经过 Platform 归一化的 `CommunicationContext`：

```json
{
  "endpoint_id": "com.example.qq",
  "external_event_id": "stable-platform-event-id",
  "external_message_id": "stable-platform-message-id",
  "conversation_ref": "opaque-conversation-reference",
  "actor_ref": "opaque-actor-reference",
  "audience_ref": "com.example.qq:conversation-hash",
  "reply_route_ref": "opaque-route-reference"
}
```

`message.received` 必须具有全部字段；event ID 标识本次外部事件，message ID 标识其所属外部消息，两者不得混用。
其他通信事件可以没有 actor 或 reply route。Platform 必须覆盖自身
`endpoint_id`，不得信任外部 notification 声称的 endpoint。原始 token、认证信息和 Provider 私有对象不得进入
CommunicationContext、Brain Context、Agent state 或模型 continuation。

`audience_ref` 是 Platform 根据 endpoint/account/conversation 确定性生成的不可解释标识。Task、通信 situation 和
跨 Task 活动投影必须保存 audience。Console 与 Dashboard 属于固定 `owner.local` audience；每个 QQ 私聊、群组、
Discord channel 或 thread 默认形成不同 audience。所有 Task 都必须有 audience：`system.tick` 和其他无通信来源的
本地系统事实使用 `system.local`；非通信 MCP 领域事件使用 `<app-package>:system`。

Brain Context 的投影规则为：

1. 当前 Agent 可以看到本 Task 的完整规范化输入。
2. 同 audience 的其他活动 Task 可以暴露经过清理的 summary，不暴露原始 actor 或平台地址。
3. 不同 audience 只暴露 Task ID、状态、预算和脱敏工作类型，不暴露 root summary、Agent assignment、last summary、
   conversation、actor 或正文。
4. Relay 不改变来源 Task 的 audience；它只新增带来源和目标 scope 的因果事实。

SOUL、活动能力目录和非通信系统事实继续全局共享。Agent state、mailbox、模型 continuation 和隐藏推理继续属于各自
Agent/Task。长期事实如何跨 audience 共享由 Memory RFC 决定。

### ReplyRoute 与 DestinationGrant

`ReplyRoute` 表示回复当前输入来源的权利，不是模型填写的地址。内建通信 Platform 或配置为受信任 connector 的
MCP communication App 是自身 route 的权威，必须在提交 ingress 前持久化 `route_ref -> private address` 映射，并
随 AMP 提供 opaque `reply_route_ref`。Kernel 接管根 AMP 时，在创建 Task 的
同一事务中保存不含私有地址的 grant 元数据：

```text
route_ref, task_id, endpoint_id, capability_id, audience_ref, operation=reply, expires_at, status
```

route ref 在 endpoint 内唯一，并且必须绑定产生事件的 account、conversation、reply capability 和到期时间。App/
Platform 对该绑定的正确性属于与其外部效果执行相同的信任边界；Aurora 不试图用另一个组件重新证明外部 conversation。
route 在连接重建后必须保持可解析直至到期，重放同一 external event 必须返回同一 route。

App/Platform 保存私有地址，Kernel 保存 Task 授权，两者以 `endpoint_id + route_ref` 关联。Kernel 验证
PublicationRequest 使用的 route 属于当前 Task、尚未过期且允许 reply；Kernel 不解析私有地址。localhost 只领取和
路由已经通过 Kernel 授权的 Publication Activity，不拥有 grant 数据库。Task 终结时 Kernel 吊销 grant；route
authority 按 TTL 清理孤立或过期 route。未受信任的普通 MCP App 不得产生 ReplyRoute。

`DestinationGrant` 表示向非来源目标发送的权利。首版目标只能来自核心或 App 配置中声明的别名；每个 grant 绑定：

```text
alias, endpoint_id, capability_id, operation, allowed_source_audiences,
target_audience_ref, configuration_hash
```

Kernel 持有以上不含私有地址的不可变配置快照；对应 Platform 持有 `alias -> opaque_address_ref` 私有绑定。组合根从
同一已验证配置构造二者，通过 Kernel 配置和 Platform 构造参数分别注入，Platform 不查询 Kernel。Kernel 在提交
Publication Activity 时重新验证 grant；Platform executor 只解析 lease 中已经授权的 alias 和 capability，不得扩大
operation 或目标范围。

模型只能看到 alias、说明、单一 operation 和目标 audience 的非敏感标签，不能看到 opaque address。首版不允许模型
自由枚举联系人、群组、频道，亦不接受模型根据自然语言自行构造 address ref。用户临时指定任意新目标、联系人发现
和确认流程由后续 RFC 决定。

`session_id` 继续作为来源相关 Task 元数据，但不得作为 ReplyRoute、DestinationGrant 或跨 Platform 地址。任何
executor 都不得根据来源 session 猜测另一个 Platform 的目标。

### PublicationRequest

通信发布使用独立的 `PublicationRequest`，并作为 `AgentDecision` 的一种主要动作。它与 model request、普通 effect、
delegation、wait、Completion 和 failure 互斥，保留每轮恰好一个主要动作。

PublicationRequest 包含：

```text
operation        reply | relay | proactive_send
route_ref        reply 时必填
destination      relay/proactive_send 时必填，只能引用 grant alias
text             非空文本
completion_mode  continue | complete_on_success
reason           proactive_send 时必填
tool_call_id     可选
continuation     可选
```

来源 provenance、source/target audience、hop count、request ID 和 agent/task identity 由 Kernel 根据根 AMP、grant 与
因果事实生成，模型不得提交或覆盖。无外部来源的自主 Task 使用 `source_audience_ref = system.local`，其
`source_endpoint_id` 和 `source_external_event_id` 为 null，并以根 AMP message ID 维持因果来源。

子 Agent 不能提交 PublicationRequest。子 Agent 如需建议对外表达，只能在 Completion artifacts 中返回严格的
proposal：

```json
{
  "type": "publication.proposal",
  "operation": "reply",
  "destination": null,
  "text": "draft text",
  "reason": null
}
```

proposal 没有任何外部权限，父级必须在后续 turn 中独立决定是否发布。

### Publication Activity 与 Task 完成

PublicationRequest 创建 `kind = publication` 的持久化 Activity。它继续扣减 Task 的现有 `max_tool_calls` 预算，
与普通 effect 共享 `effect_concurrency` 和租约上限，但使用独立的领取 DTO、回执类型和授权校验。每个 Agent 仍最多
拥有一个活跃 Activity。

闭环为：

```text
root PublicationRequest
  -> publication Activity
  -> localhost publication dispatcher
  -> 唯一 endpoint Platform executor
  -> PublicationOutcome
  -> publication.succeeded | publication.failed | publication.delivery_unknown AMP
  -> Kernel 恢复 root 或完成 Task
```

回执处理规则为：

- `continue + succeeded`：完成 Activity，以新邮箱消息恢复 root。
- `complete_on_success + succeeded`：完成 Activity、根 Agent 和 Task，并取消监督树其余工作。
- `failed`：无论 completion mode，都以新邮箱消息恢复 root。
- `delivery_unknown`：无论 completion mode，都恢复 root，禁止自动重试，且不得完成 Task。

continuation 是可选的。有模型 tool continuation 时，ToolAgent 追加结构化 publication result；没有 continuation 时，
receipt 作为独立 mailbox 事实触发新的模型 turn。`complete_on_success` 不要求 continuation。

普通单条回复使用 `complete_on_success`。分两次回复使用第一条 `continue` 和第二条
`complete_on_success`。向另一个端点发送后再回复来源，使用一次 `relay/continue` 和一次
`reply/complete_on_success`。一个 Task 的多次发布不是原子事务，每一条都有独立 request ID、outcome 和取消边界。

当前 `terminal` effect 不再承担发布权限或 Task 完成语义。Console、Dashboard 与通信 MCP App 必须使用
Publication；普通 effect 在成功或失败后恢复请求 Agent，Task 只能由显式 Completion 或根 Publication 的
`complete_on_success` 结束。当前配置没有 terminal MCP 工具，因此不保留双语义兼容期。

### Publication capability 与授权

`CapabilityDescriptor` 必须区分 `effect` 与 `publication`。Publication descriptor 声明 capability ID、endpoint ID、
恰好一个 operation、参数 schema 和 `root_only = true`；动态连接健康不改变启动期不可变 catalog，运行中断线形成普通
failed 或 delivery_unknown outcome。

Kernel 在每个 turn 根据 profile、启动期 catalog、当前 Task ReplyRoute、不可变 DestinationGrant 和 source audience
生成只读的有效 publication descriptor 投影，并放入 AgentContext。ToolAgent 只能把该投影转换成模型工具，不查询
Kernel、Platform 或配置。Kernel 接收 PublicationRequest 时必须重新执行同一授权，模型能看到工具不构成授权依据。
这里的 active 只表示端点在启动时已启用并成功加入不可变 catalog，不表示瞬时连接健康。

有效授权按 operation 分别计算：

```text
reply:
  profile capability
  ∩ active publication catalog
  ∩ current Task ReplyRoute grant

relay/proactive_send:
  profile capability
  ∩ active publication catalog
  ∩ DestinationGrant
  ∩ source audience policy
  ∩ requested operation
```

来源 endpoint 不得自动屏蔽其他已授权 endpoint。QQ 输入可以触发 Discord relay，但 QQ ReplyRoute 只能用于 QQ
reply。禁用 Platform 或 App 不得注册 endpoint executor、route resolver 或 publication capability。

### 幂等、未知投递与回流

每个通信 Platform 必须根据 `endpoint_id + external_event_id` 确定性生成或恢复 AMP `message_id`，同一外部事件重放
不得创建第二个 Task。没有稳定 external event ID 的事件不得归一化为通信 `message.received`。

Publication executor 必须在外部调用前持久化 dispatch-start，并尽可能把 publication request ID 作为外部客户端
幂等键。明确成功记录 `external_message_id`；明确拒绝形成 failed；进程在 dispatch-start 后、确定结果前中断形成
delivery_unknown。delivery_unknown 只有在 Platform 能用幂等键查询或安全重试时才可 reconciliation，否则必须由
root 向用户说明不确定性或等待人工处理。

Publication 的重启恢复取代 RFC 0012 对普通 PROCESSING Activity 直接生成 `interrupted_by_restart` 的规则：

1. 尚为 PENDING 的 Publication 可以正常领取。
2. 重启发现 PROCESSING Publication 时，Kernel 将其保留为待协调恢复，不先生成失败消息。
3. localhost 通过 publication recovery port 把 request ID 交给对应 executor；不得读取 Platform 数据库。
4. executor 无 dispatch-start 记录时返回 `failed/interrupted_before_dispatch`，因为外部调用在账本落盘前被禁止。
5. executor 有 accepted/failed 终态时重放同一幂等 outcome；有 dispatch-start 但无终态时返回 delivery_unknown。
6. localhost 以确定性 AMP message ID 提交恢复 outcome；重复恢复不得产生第二条 mailbox receipt。

Platform 必须根据 endpoint 与已发送 message ledger 中的 external message ID 识别 Aurora 自发消息回流，不得只信任
connector 提供的 self-authored 布尔值。自发回流可以形成 delivery update，但不得创建普通用户 Task。Relay
provenance 记录不可变 source endpoint、source event、destination endpoint 和 hop；首版最大 hop 为一，不能自动
转发回来源。

## 配置约束

- Agent profile 继续用现有 `capabilities` 同时声明 effect 与 publication 授权上限，不新增第二份能力列表。
- `config/aurora.toml` 新增严格 `[communication]`：`reply_route_ttl_seconds` 为正数，`relay_hop_limit` 首版必须为 `1`。
- Console 和 Dashboard 的 endpoint、owner audience 与 publication descriptor 由内建 Platform 固定声明，不进入偏好配置。
- `config/aurora.toml` 的 `[dashboard.owner]` 必须声明稳定 `username`。该规范化用户名只能绑定一个 Dashboard 账号；
  未注册时 Dashboard 可以运行但不能产生 Bot ingress，绑定后不得重命名或删除。Bot publication 固定投递该 owner。
- MCP communication endpoint、publication 工具与 destination alias 的严格配置由 RFC 0016 定义。
- `config/preference.toml` 仍只选择 Platform 启动和本地体验，不得授权 route、destination、actor 或跨平台发送。
- 未知 endpoint、operation、route、destination alias 或策略键必须确定性失败。

## 与既有 RFC 的关系

本 RFC 在接受后：

- 部分取代 RFC 0012 以 `terminal` 同时表达 root-only 与 Task 终止的条款；保留同构 Agent、监督树、共享预算、
  单 turn、单 Activity 和根 Task 结束时取消整棵树。
- 明确 RFC 0012 的 Agent 是同一 Aurora 人格下的认知工作单元，不按 Platform 复制；不改变不同 Agent 可并行的决定。
- 收紧 RFC 0012 的全局可信人格域：人格和系统事实全局共享，外部 audience 内容按本 RFC 过滤。
- 取代 RFC 0010 以 `dashboard:user:<id>` 作为 Kernel 回复地址的条款；Dashboard 对 Aurora 提供固定 owner endpoint。
  RFC 0010 的平台私有鉴权与消息持久化可以继续存在，但非 owner 用户不得触发 Aurora Bot Task。
- 扩展 RFC 0003 的 AMP 通信上下文、外部事件去重和三态 Publication 回执；AMP 信封和因果边界继续有效。
- 扩展 RFC 0014 的 capability catalog 与效果闭环；Platform 唯一执行权、localhost 窄端口、单 Runtime 和精确平台
  组合继续有效。

## 非目标

- 长期记忆、身份自动合并、联系人目录搜索、用户临时地址 grant 和跨 tenant 联邦。
- Provider parallel tool calls、复杂 Agent join、quorum、截止时间和全局 root attention lease。
- 多条 Publication 的原子提交、持续双向桥接或自动跨 audience 信息同步。
- 附件、编辑、删除、reaction 和富媒体跨 Platform 转换。
- MCP 多账号、同 App 多 endpoint、远端工具重命名和热插拔；这些不属于核心 Agent Publication 契约。
- Platform 接收成功只表示投递已被目标媒介接受，不表示外部人类已读。

## 验收标准

1. Console 或 Dashboard 的一个根 Task 可以依次发布两条独立消息，第一条恢复 root，第二条成功后完成 Task。
2. 单条普通回复仍只显示和持久化一次，并在 Platform 成功回执后完成 Task。
3. 子 Agent 无法提交 PublicationRequest，只能返回无权限的规范 proposal artifact。
4. Publication 使用独立 Activity kind 和三态回执，扣现有 tool budget 并共享 effect concurrency。
5. failed 和 delivery_unknown 都恢复 root；unknown 不自动重试，也不满足 complete_on_success。
6. reply route 在 Task 创建时绑定、终结时吊销，不能通过替换 capability、endpoint 或模型参数改投其他 conversation。
7. relay/proactive 只能选择配置 grant，来源 reply route 不能充当跨 Platform destination。
8. Console 与 Dashboard 使用固定 endpoint，Agent 和 Kernel 不解析 Dashboard 私有用户 ID。
9. 不同 audience 的 Brain Context 不暴露正文、actor、conversation、root summary、assignment 或 last summary。
10. 每次 Publication 可追溯到根 AMP，并记录独立 request ID、outcome、外部 message ID 或 unknown 状态。
11. 自发消息回流不创建普通用户 Task，Relay hop 超过一或返回来源时确定性拒绝。
12. Kernel 不导入 Platform，Platform 不修改 Kernel 状态，localhost 不持有平台私有地址。
