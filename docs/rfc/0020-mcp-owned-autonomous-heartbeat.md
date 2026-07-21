# RFC 0020：内建 MCP 所有的自主心跳

状态：已接受
日期：2026-07-22

## 背景

此前 localhost `CognitiveScheduler` 同时负责自主模型日额度、基于 Task 结果的退避和 `system.tick` 的产生。这使
Runtime 在没有 MCP Platform 的 Console、Dashboard 或 headless 调试组合中仍会自行产生认知工作，且 Agent 无法以
普通 Tool 表达“休息到何时”。

Aurora 的内建 Clock 已经是一个持久化、可通知的 MCP App。自主节律应当成为该内建 App 的能力；Runtime 只消费
统一 AMP 事实并保持 Task、取消与预算边界。

## 决策

### Clock heartbeat

`org.aurora.clock` 新增下列标准 MCP Tool：

- `start_heartbeat`：仅由 MCP Platform 在 Clock 成功发现后调用，为本次运行建立或恢复 fallback heartbeat；
- `sleep(seconds)`：Agent 选择下一次自主醒来的目标时间。

Clock 在 `data/app_data/org.aurora.clock/tasks.json` 持久化一个唯一 heartbeat。到期时它使用既有
`notifications/message` 的 `aurora/event` 形态发送 `system.tick`；不增加 notification schema、签名机制或新的
Runtime ingress 分支。Clock 发出 tick 后必须按配置的 fallback interval 安排下一次 heartbeat。成功的 `sleep` 必须
替换该唯一 heartbeat；普通 alarm 和 timer 保持原有独立行为。

Clock heartbeat 的 Tool 调用和通知均经过现有 MCP Platform。MCPPlatform 发现内建 Clock 后必须调用
`start_heartbeat`；未选中 MCP Platform 或 Clock 未启用、未连接时，不得产生自主 tick。

### Runtime 边界

localhost Runtime 不得计算、持久化、退避、保留或发射自主 tick。它继续将任何已有 ingress 收到的 `system.tick`
作为 autonomous Task，并在非 tick 外部活动到来时取消进行中的 autonomous Task。

自主日模型调用和 token 上限仍由 localhost 的 `AutonomyQuota` 持久化并执行；它不包含 tick 时间、interval 或
Task 结果退避状态。调试 status 使用 `autonomy_quota` 公开该状态，不再公开 `scheduler`。

### 配置

`runtime.scheduler` 被 `runtime.autonomy` 取代：

```toml
[runtime.autonomy]
scan_seconds = 1.0
heartbeat_initial_seconds = 30.0
heartbeat_min_seconds = 30.0
heartbeat_max_seconds = 1800.0
autonomous_daily_model_calls = 24
autonomous_daily_tokens = 100000
```

`scan_seconds` 是 Runtime 等待外部工作时的最大睡眠时间；其余 heartbeat 参数由 MCPPlatform 作为内建 Clock 的
子进程环境传入。Clock 必须将 Agent 请求的 `sleep` 时长夹在 min/max 范围中。`idle_multiplier` 和
`action_cooldown_seconds` 不再存在。

## 约束与非目标

- 不改变 AMP、MCP notification、Kernel 对 `system.tick` 的 autonomous 分类或 Tool outcome 契约。
- 不要求第三方 MCP Server 实现 Clock Tool；`start_heartbeat` 是内建 `org.aurora.clock` 的明确能力。
- 不试图从模型输出拟合心理状态；Agent 通过 `sleep(seconds)` 显式表达节律选择，fallback heartbeat 保证持续运行。
- Clock 不读取 Kernel 状态、Task、模型用量或 Platform 私有对象。
- 未启用 MCP 的进程是无自动心跳的手动调试组合；仍可通过既有 debug/AMP 入口手动提交 `system.tick`。

## 与既有 RFC 的关系

- 部分取代 RFC 0012 和 RFC 0014 中 localhost scheduler 负责主动节律的条款；保留 localhost 的模型 Activity
  dispatcher、统一 ingress 和外部活动取消语义。
- 扩展 RFC 0018 的内建 MCP Tool：Clock 仍使用标准 tools/list、tools/call 和自由 notification，不为第三方 Server
  引入新惯例。
- 保留 RFC 0003 的 `system.tick` AMP 领域事实及 Kernel 因果边界。

## 验收标准

1. 未选择 MCP 或 Clock 不可用时，Runtime 不会自行提交 `system.tick`。
2. Clock 启动后持久化并发出 fallback `system.tick`；重启会恢复未到期 heartbeat。
3. `org.aurora.clock.sleep` 成功后替换下一次 heartbeat，并将实际间隔限制在配置的最小和最大值内。
4. Clock 发出的 `system.tick` 经不变的 MCP notification ingress 创建 autonomous Task。
5. 普通 alarm/timer 仍产生原有事件，并以非 tick 外部活动取消正在运行的 autonomous Task。
6. Runtime 持久化并执行自主日模型/token 配额，但不存在 scheduler tick 状态、Task 结果退避或 interval 计算。
