# 0209：Agent 全同构——Triage 入口与委派唯一化

状态：已接受
日期：2026-08-07
来源：RFC 0207/0208 的推论；取代 RFC 0202 的 TriagePolicy 旁路与特殊 admit 路径；先决条件是 RFC 0205 的派生等待状态与类型化 AgentDecision

## 问题

"以 Agent 为中心"的架构存在一个最显著的例外：**Triage 不是 Agent**。

- `StructuredTriagePolicy` 是无状态 policy（`request`/`resolve`），engine 在 `_triage_inbox` 直接调用 `_model_provider.complete`，绕过 claim、邮箱、Activity 与因果链路——triage 没有 agent 实例、没有消息、没有状态、没有崩溃恢复。
- triage→root 是特殊 `apply_triage` admit，与 root→worker 的 delegate 是两套派发机制。
- 上下文与决策各有两套 DTO（`TriageBatch`/`TriageDecision` 对 `AgentContext`/`AgentDecision`）。
- root 首轮 `task.started` 与 worker 首轮 `agent.assigned` 之外，triage 没有任何消息类型。

## 决定

### 1. Agent 全同构：三元组实例化

系统只通过一个 schema 实例化一切 Agent：

1. **上下文**：engine 按 profile 从运行态构造（入口 agent = 批次投影 + 记忆；委派 agent = assignment + 记忆 + 自己的结果）；
2. **工具权限域**：`AgentProfile.capabilities`（platform / builtin / delegate 等域，可能为空）；
3. **逻辑实现类**：`AgentProfile.implementation`。

`AgentProfile` 即三元组的声明载体。triage、本体意识、worker、记忆 agent 都是同一 schema 的实例，走同一条 claim → turn → 决策 → 派发链路。

### 2. Task 从 Triage 开始

- 防抖批次到期 → 创建轻量 Task，**triage agent 是该 Task 的根 agent（depth 0）**，首轮上下文 = 批次投影 + 记忆快照（复用 `task.started` 消息类型与 `handle_claim` 路径）。
- triage 决策统一为 `AgentDecision`：
  - **process** → 委派本体意识（`builtin.gate`，depth 1，首轮 `agent.assigned`）；triage 通过既有 `wait_for_children` 等待回报后完成，Task 终态判定、预算、因果记录零特判。
  - **defer** → 批次回到 `DEFERRED`（`available_at = now + defer_seconds`，受 `TriageLimits` 钳制），Task 终态归档；批次到期后**每次尝试都是一个新的轻量 Task**，同一会话的多次尝试各留审计记录。
  - **discard** → 删除批次原始数据，Task 终态归档。
- RFC 0202 的"admit 直接创建 Root Task"被"triage 创建 Task + 统一委派"取代。每次 triage 尝试独立成 Task，使 defer/discard 也有完整因果记录与崩溃恢复。

### 3. AgentDecision 新增 transitions

- `defer`：携带 `defer_seconds`（钳制到 `TriageLimits` 上下界）。
- `discard`：无载荷。
- `AgentProfile` 新增 `triage_control: bool = False`；只有声明该字段的 profile（`builtin.triage`）才被授权发出这两种 transition。
- `AgentDecision` 新增可选载荷 `memory_candidates: tuple[str, ...] = ()`（非 transition，不参与单原子迁移校验）；triage 的 `memory_candidate` 迁移到此，engine 终态投影时采集——RFC 0202 的长期事实行为不变。

### 4. Triage 的逻辑类与权限域

- 新增 `builtin.triage` profile：`implementation = "src.agents.handler:TriageAgent"`（新逻辑类：无工具、快模型、结构化输出、单轮），`capabilities = ∅`（空权限域），`model_role = "fast"`，`triage_control = true`，`can_delegate = true`，`child_profiles = ["builtin.gate"]`。
- triage 的模型调用走 model Activity——与普通 Agent 完全同构，可审计、可恢复、受并发与预算约束。
- **fail-open 保留**：triage 模型失败时，engine 以确定性规则直接委派本体意识（摘要 = 事件拼接），不静默丢失用户输入。
- 已知的供应商瞬时噪声仍在 Platform/App 边界用确定性规则过滤（RFC 0202 不变），triage 内部不做规则判断。

### 5. 契约收敛

- 移除 `TriagePolicy` Protocol 与 `TriageDecision` DTO；`engine` 构造签名不再接收 `triage_policy`。
- `TriageBatch` / `InboxEvent` / `TriageLimits` 保留——它们是 triage 首轮上下文的投影来源与防抖/批次上界。

### 6. 术语与预算

- Task 根 agent = 入口 triage agent；**本体意识是 triage 委派的第一个子 agent**。
- 委派链深度预算顺延一层（triage=0，gate=1，worker≤2 起）；`max_agents_per_task` / `max_children_per_agent` 语义不变。
- Task 预算（interactive / autonomous）在 triage 创建 Task 时按批次特征确定（判定保留在批次投影中）。

## 结果

- 三种 Agent 完全同构：委派是唯一派发机制，admit 从引擎中消失。
- triage 决策全链路可审计、崩溃恢复自然覆盖（中断的 triage 恢复后继续其决策）。
- 噪声批次 = 1 个轻量 Task（1 个 triage agent + 1 次 model Activity），仍远优于逐条事件创建 Task。

## 兼容性

- 契约变更：`TriagePolicy`/`TriageDecision` 移除；`AgentDecision` 增加字段（默认值保持向后兼容）；`AgentProfile` 增加 `triage_control`（默认 False）。
- SQLite Schema 无需结构变更：复用 tasks / agents / activities；defer 语义映射到 `inbox_events.DEFERRED`。
- 归档格式不变（`root_agent_id` 指向入口 agent）；旧工作区无需迁移，行为等价。
