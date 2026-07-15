# RFC 0008：首轮认知图、Episode 与主动节律

状态：已接受
日期：2026-07-15

## 背景

RFC 0001 的单节点最小闭环与 RFC 0005 的规范化模型调用完成了可审计因果链，但现有实现仍在一个
Kernel 周期内等待模型、依赖模型输出 JSON 决策，并且只能由开发者手动推进周期。它不能表达原生
Tool Call、跨周期工具续跑、复杂度级联或无外界输入时的自主认知。

本 RFC 部分取代 RFC 0001 的“最小运行图”和“周期与自环”首版条款，并取代 RFC 0005 中
“首版 LiteLLM 适配器拒绝 native”的限制。未被本 RFC 改写的模块边界、AMP、配置、效果和模型
审计契约继续有效。

## 决策

### 有界 Episode 与认知图

每个外部根事件或 `system.tick` 创建独立 episode。首轮不跨 episode 保存会话历史；episode 内可以
跨周期保存模型输出项、Tool Call 与效果回执，直到发布、静默、取消、失败或预算耗尽。

首轮图为：

```text
message.received / system.tick -> builtin.fast_gate
builtin.fast_gate -> effect.requested | cognition.escalated | episode.ended
cognition.escalated -> builtin.native_agent
model.completed / model.failed / effect receipt -> @continuation
```

`@continuation` 是 Kernel 内部路由，不读取 AMP payload 中的目标。模型请求与非终态效果请求必须
记录发起节点；完成事件最早在下一周期回到该节点。所有 continuation edge 必须推进 episode round，
并受模型调用数、工具调用数、跳数和持续时间共同限制。

Kernel 在 `process/episodes/` 维护原子 JSON `EpisodeSnapshot`，包含根记录、活动节点、状态、round、
模型/工具计数、预算、规范化 transcript 和终止原因。记录仍是因果事实来源；snapshot 是 Kernel
拥有的运行状态，不是记忆节点或共享可写文件。结束后的 snapshot 移入 `archive/episodes/`。

### 异步模型能力

节点不得在一次执行中等待 Provider 网络调用。节点发布 `model.requested` 后立即返回；Kernel 周期外的
model dispatcher 执行请求并发布 `model.completed` 或 `model.failed`。模型调用是 Kernel 授权的内部
能力，不是 Platform effect。

运行时重启后，遗留的 `PROCESSING model.requested` 必须失败为 `interrupted_by_restart`，默认不重试。
自主模型请求使用 `on_external_activity` 取消策略；交互请求默认 `never`。全局首版模型并发为一，交互
请求优先于自主请求。

### 双模型通道与 Tool IR

`ModelRequest` 支持 tools、tool choice、串行策略、continuation、取消策略和受控 Provider 参数；
`ModelResult` 返回规范化文本、Tool Call、finish reason、用量、费用和可序列化 continuation。

- `chat_completions` 通道将统一 Tool IR 映射为 Provider 原生 `tools/tool_choice`，并重放 assistant
  Tool Call、推理字段与 tool result。
- `responses` 通道使用 Provider Responses endpoint。首版 OpenAI 请求使用 `store=false`、
  `parallel_tool_calls=false`，并在需要推理连续性时请求 encrypted reasoning；续跑重放完整 output
  items 与 `function_call_output`，不依赖 `previous_response_id`。

原生 Python 响应对象不得落盘。Provider 专有 continuation 只能保存为带 provider/channel 标识的规范
JSON。调用方不得通过参数透传覆盖模型、密钥、Provider 地址、tools、存储和并行策略。

模型产生普通文本不等于发布。fast gate 只能通过 Platform 终态能力完成发布，通过内部
`aurora.cognition.escalate` Tool 升级，或静默结束。所有外部 Tool Call 在生成 `effect.requested` 前由
Kernel 再次校验节点授权、能力存在与参数 JSON Schema。

### Platform 能力目录

Platform 启动后向 Kernel 安装不可变 `CapabilityCatalogSnapshot`。每个能力包含 ID、描述、参数
JSON Schema 和 `result_mode`：

- `resume`：成功或失败回执均恢复发起节点。
- `terminal`：成功回执结束 episode；失败回执仍恢复发起节点。

MCP App 的 TOML allowlist 使用 `[[app.tool]]` 表声明工具名与 result mode。发现结果必须与该表完全
一致。`org.aurora.console.send_message` 为 terminal；首轮 Clock 工具为 resume。

### 主动节律

localhost 运行用例拥有一个常驻 scheduler。轻量 inbox 扫描不产生模型调用；到期时 Kernel 创建普通
`system.tick`。默认初始空闲间隔为 30 秒，连续静默按两倍退避至 30 分钟，自主效果后冷却 5 分钟，
外部输入立即唤醒并重置节律。

同时只允许一个自主 episode。自主 episode 默认最多三次模型调用、两次工具调用和 120 秒；UTC 日
额度为 24 次模型调用或 100000 总 token。交互 episode 默认最多八次模型调用、六次工具调用和
300 秒。额度与节律均由 TOML 配置并持久化在 `process/scheduler-state.json`。

`serve`、`console` 和组合入口必须共享一个进程内 `AuroraRuntime` 与一个 Kernel 所有者；不得启动两个
运行时同时操作同一工作区。

RFC 0006 的开发 API 增加两个只读端点：`GET /v1/debug/status` 返回周期、scheduler、活动 episode 与
model dispatcher 状态；`GET /v1/debug/episodes/{episode_id}` 返回已脱敏 episode snapshot 或 404。
`POST /v1/debug/cycles` 保留为强制调试周期，并与 scheduler 使用同一运行时锁。

## 配置与接口约束

- 模型角色声明 `endpoint = "chat_completions" | "responses"`；Responses 角色还须声明
  `native_responses` 能力。
- `nodes.toml` edge 可以使用 `target = "@continuation"`，该 edge 必须设置
  `advances_round = true`。
- App 工具声明使用 `[[app.tool]] name/result_mode`；其他 result mode 在启动前失败。
- 所有新增运行时文件仍位于既有 `inbox/process/archive` 三目录内，且使用临时文件加原子改名。

## 非目标

- 长期记忆、跨 episode session 历史、沙箱或提示词节点化。
- 多 Tool Call 并行 join、第三方 Python 插件自动发现、QQ/Discord/OneBot 适配。
- Dashboard 前端、archive 压缩或 Provider 托管 Conversation 对象。

## 验收标准

1. 简单消息可由 fast gate 通过原生 Tool Call 发布；复杂消息可升级到 Responses agent。
2. 模型请求、模型完成、效果请求和效果回执分别位于不同因果阶段，新产物不能被同周期节点消费。
3. 普通工具回执恢复同一 episode；terminal 成功关闭 episode，terminal 失败恢复模型。
4. 空闲运行会产生受预算约束的 tick，并在静默后退避；外部输入可以唤醒并取消自主模型调用。
5. 重放、重启、非法 Tool Call 或预算耗尽均不会产生重复 Platform 效果。
6. Chat 与 Responses 通道只持久化规范 JSON，且统一记录用量、费用和诊断。

## 迁移影响

`builtin.model_decide` 的 JSON 决策协议保留为兼容候选但不再进入默认图。现有 `allowed_tools` 配置迁移为
`[[app.tool]]`；现有模型角色必须补充 endpoint。localhost 的组合 CLI 从双进程改为单运行时编排。
