# 0207：Multiagent 委派链与同源记忆

状态：已接受（注意力 agent 的承载形态已被 RFC 0209 取代）
日期：2026-08-07
来源：固化 RFC 0202 的 Triage→Root→子代理拓扑为三级认知角色，并为记忆补充唯一缺失的主动写入路径；先决条件是 RFC 0202 的三层信息存储与 RFC 0205 的类型化 AgentDecision
> 注：RFC 0209 将注意力 agent 从 `StructuredTriagePolicy` 改为同构的入口 triage agent；
> 本 RFC 的委派链、全员被动记忆与记忆同源语义不变。

## 问题

Multiagent 拓扑（注意力初筛 → 本体意识 → 专精 worker）已分散实现，但缺少单一文档定义，且有两个实际缺口：

- **主动记忆没有出口**：记忆只有一条被动写入路径（Task 终态投影）。Agent 在任务中途无法主动要求"记住这件事"——事实要等到任务结束才被压缩投影，Triage 提取的 `memory_candidate` 也只在终态才落库。
- **同源未固化**：若主动记忆以新存储、新契约实现，将与自动投影分叉成两套事实。被动与主动记忆必须读写同一份存储，事实才不会分裂。

## 决定

### 1. 三级认知角色（委派链固化）

| 角色 | 承担者 | 职责 | 委派方式 |
| --- | --- | --- | --- |
| 注意力 agent | `StructuredTriagePolicy` | 无工具、快模型的初筛：process / defer / discard，并提取 `memory_candidate` | 通过批次接纳（admit）交给本体意识，不使用 delegate 工具 |
| 本体意识（Root） | Root Task + `builtin.root` | admitted batch 的唯一入口；可独立完成，或显式委派 | `aurora.agent.delegate` |
| worker | 同构 ToolAgent + `builtin.worker` | 执行专精任务；只接收 assignment、自己的记忆快照与自己的结果 | 由本体意识（或获准的中间 Agent）委派 |
| 记忆 agent（新增） | 同构 ToolAgent + `builtin.memory` | 唯一获权执行主动记忆写入 | 由本体意识（或获准的中间 Agent）委派 |

### 2. 被动记忆：全体 Agent 共享

- `handle_claim` 对每个被 claim 的 Agent（Root、worker、记忆 agent 一视同仁）注入 session 作用域的 `MemoryContextSnapshot`；子代理不继承 Root 的事件历史，但记忆快照人人有份。
- 记忆是"被记住"而非"决定记住"——Agent 不做记忆决策，读取路径唯一（`MemoryStore.recall`）。

### 3. 主动记忆：可委派的记忆 agent

- 新增 profile `builtin.memory`：`capabilities = ["aurora.memory.remember"]`、`can_delegate = false`；本体意识等获准委派的 profile 将其列入 `child_profiles`。
- 本体意识通过 `aurora.agent.delegate` 委派"记住 X"给记忆 agent；记忆 agent 完成时把确认摘要作为 child report 回报，走既有因果与审计路径。
- 新增主动能力 `MemoryCapability`（`src/agents/capabilities/memory.py`）：定义 `aurora.memory.remember` 工具（参数 `content`、可选 `fact_candidates`），只生成 `ToolRequest`，不持有任何存储实现——与 speech 同构。工具定义按 `context.profile.capabilities` 自门控，仅获权 profile 可见。
- 新增执行器 `MemoryToolExecutor`（`src/memory/executor.py`）：实现 `contracts.tool.ToolExecutor`，内部调用**同一个** `MemoryService`；scope 取自 `ToolExecutionRequest.session_id`；幂等键为 tool request_id（复用 `memory_receipts`，恢复重放天然去重）。
- `aurora` 组合：构造 `MemoryService` → `MemoryToolExecutor` → 作为 `ToolExecutorBinding` 与平台工具同路注入 `ToolRegistry`；`MemoryCapability` 随 `_build_capabilities()` 安装到 handler。授权仍由 `profile.capabilities` 门控。
- 主动写入的唯一入口是记忆 agent：Root/worker 的 capabilities **不得包含** `aurora.memory.remember`。由于 MCP 工具名在运行时动态发现，`"*"` 无法收敛为静态显式列表，配置采用**排除语义**：`capabilities = ["*", "!aurora.memory.remember"]`（`!` 前缀否定优先于 `*` 与前缀通配，仅此一种新增语义）。
- `MemoryCapability.tool_definitions()` 返回空元组：工具定义由记忆执行器的 catalog descriptor 单一提供（`handle_claim` 已按 profile 注入 descriptor，重复提供会触发 `DUPLICATE_TOOL_IDS`）；能力类只负责参数校验与 ToolRequest 构造，授权仍由 `profile.capabilities` 门控。

### 4. 记忆同源

- 唯一存储与唯一契约：`MemoryStore` Port + `memory.sqlite3`（`MemoryService`），`MemoryEntry` / `MemoryQuery` 是唯一跨层类型。
- 三条写入路径全部落到同一 `MemoryService`：
  1. Task 终态投影（engine `_remember`，被动）；
  2. Triage `memory_candidate`（随终态投影携带，不变）；
  3. 记忆 agent 主动写入（ToolRegistry → `MemoryToolExecutor` → `MemoryService.remember`）。
- 禁止为主动记忆另建存储、Schema 或第二套契约。

### 5. 边界

- `agents` 只依赖 contracts（`MemoryCapability` 无存储依赖，只产出 ToolRequest）；
- `memory` 新增 `ToolExecutor` 实现（仍只依赖 contracts + utils）；
- `contracts.memory` 与 `contracts.tool` 均不变；engine 不改。

## 结果

- Agent 可在任务中途主动固化事实，不再依赖任务终态投影。
- 被动与主动记忆收敛到同一 SQLite，事实不会分叉；主动写入复用委派、因果、预算与审计的全部既有机制。
- 记忆 agent 是普通 worker 的一员，无需任何新引擎机制。

## 兼容性

- 新增 profile 与工具为纯增量；未声明 `builtin.memory` 的旧配置无法委派记忆 agent（`child_profiles` 引用校验在委派授权时失败），不影响既有 profile。
- 存储 Schema 不变（复用 `memory_receipts` / `session_memory` / `durable_facts`），被动记忆行为不变。
- `contracts` 无任何破坏性变更。
