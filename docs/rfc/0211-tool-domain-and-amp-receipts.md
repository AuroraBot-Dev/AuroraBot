# 0211：工具域统一与 AMP 化工具回执

状态：已接受
日期：2026-08-07
来源：RFC 0203/0207/0208 的工具链路收敛执行决定；完整重构工具调用机制
先决条件：RFC 0210（单进程无租约运行时）、RFC 0209（能力统一为 ToolExecutor）

## 问题

工具链路存在三组不一致：

1. **能力 ID 命名混乱**：`org.aurora.dashboard.send`、`{app.package}.{tool}`（如 `org.aurora.clock.get_time`）、`aurora.memory.remember`、`aurora.agent.delegate`、`tts.speak`——没有统一的域规范，"域.方法"契约不可预测。
2. **回执双轨**：工具结果通过内部完成端口（`ToolCompletionPort`/`complete_tool`）回 engine，而外部事件统一走 AMP——两个通道、两套幂等逻辑、平台需要理解内部协议。
3. **中转复杂度**：`ToolLease`（活动行→租约→请求）、`RecoveryBinding` 协议、`ToolQueuePort`/`ToolCompletionPort` 两个端口协议——为异步与恢复设计的中间层多于必要。

## 决定

### 1. 工具域命名规范（线缆契约）

能力 ID 一律以 `aur.` 开头，格式 `aur.<域>.<注册名>.<方法>`：

| 域 | 格式 | 示例（现状 → 新） |
| --- | --- | --- |
| 平台 | `aur.<平台注册名>.<方法>` | `org.aurora.dashboard.send` → `aur.dashboard.send` |
| 平台 MCP | `aur.mcp.<app_package>.<tool>` | `org.aurora.clock.get_time` → `aur.mcp.org.aurora.clock.get_time`（app_package 保持现状，不改变 MCP 连接标识） |
| 服务 | `aur.serv.<服务名>.<方法>` | `aurora.memory.remember` → `aur.serv.memory.remember` |
| Agent 内建 | `aur.agent.<方法>` | `aurora.agent.delegate` → `aur.agent.delegate`；`tts.speak` → `aur.agent.speech` |
| 未来 | — | `aur.serv.sandbox.*`、`aur.serv.console.*` |

规则：**来源决定前缀**（dashboard/mcp=平台、serv=服务、agent=内建），**ID 决定路由**（ToolRegistry 一对一），**profile.capabilities 决定授权**（`!` 排除与通配语义不变）。

### 2. 单一回执通道：工具结果 = AMP

- 平台/服务 executor 执行完成后，**通过注入的 `ExternalAmpIngressPort.submit_amp` 提交 `tool.{status}` AMP**，payload 携带 `request_id`（活动幂等键）、capability、result/error、source。
- `submit_amp` 开放 `tool.succeeded/failed/unknown` 类型（从 RESERVED 移除）；摄入路径识别后不写 inbox_events，直接匹配活动。
- 新 store 方法 `consume_tool_receipt(amp)`：按 `request_id` 匹配活动 → 幂等（causal_events 已存在 `(correlation_id=request_id, type=tool.{status})` 则忽略）→ 完成活动 → 投递 agent 消息；`complete_task=True` 且成功时**存储层直接完成 agent**（RFC 0203 语义保留）。
- 删除 `complete_tool`（engine）、`ToolCompletionPort`、`complete_tool_activity` 的引擎内部调用路径（逻辑并入 `consume_tool_receipt`）。

### 3. 协议简化

- `ToolExecutor.execute_tool(request) → None`：**执行并提交回执 AMP**，不再返回结果（结果只经 AMP 回 engine）。
- 删除 `ToolLease`：活动行直接构造 `ToolExecutionRequest`。
- 删除 `RecoveryBinding` 协议：恢复 = 重新派发执行。
- `ToolRegistry` 直接持有 store：职责收敛为「绑定（catalog 路由表）+ 派发（活动 → executor）+ 恢复（PROCESSING 重派）」；不再依赖 `ToolQueuePort`/`ToolCompletionPort`。
- `contracts/ports.py` 删除 `ToolQueuePort`/`ToolCompletionPort`；engine 不再实现这两个端口。

### 4. 恢复语义

- 工具活动 PROCESSING 且任务活跃：重启后由 `ToolRegistry.recover_pending()` **重新派发执行**（executor 重新执行并提交回执；request_id 幂等保证回执去重、不重复投递 agent 消息）。
- 删除 UNKNOWN 回执与 recovery binding。

### 5. 保留

- 工具活动表（异步工具执行中的恢复依据）、`request_id`/`idempotency_key` 幂等、模型/工具预算计数、`complete_task` 语义、权限域（`*`/`!`/通配/精确）与 catalog 按 profile 过滤。

## 结果

- 模型看到的工具定义 = 完整 tool 域，一律 `aur.*`，可预测。
- 所有外部世界进 engine 只有一条通道（AMP）；工具回执与用户事件同一套幂等与审计。
- 工具协议面缩小：删 2 个端口、1 个中转结构、1 个恢复协议；ToolRegistry 变成纯路由表 + 派发器。

## 兼容性

- contracts：`tool.py` 改 `ToolExecutor` 签名、删 `ToolLease`/`RecoveryBinding`；`ports.py` 删两端口；AMP 类型开放。
- platform：dashboard/mcp adapter 执行后构造并提交回执 AMP（mcp 已有 `_ingress.submit_amp` 通道）。
- memory：`MemoryToolExecutor` 同步执行后提交回执 AMP（走同一通道，同源不变）。
- agents：capabilities 工具名改 `aur.agent.*`；`agents.toml` 的 `!` 排除引用更新。
- engine：ingress 识别 tool.* AMP、store 新增 `consume_tool_receipt`、ToolRegistry 重构、runtime 删 complete_tool。
- 测试：命名映射、AMP 回执链路、幂等与恢复测试更新。
