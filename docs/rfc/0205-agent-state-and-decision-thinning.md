# 0205：Agent 状态机收敛与决策链路扁平化

状态：草案
日期：2026-08-05
来源：RFC 0200/0203 的运行时细化；先决条件是已实现的类型化 AgentDecision（model_request 为 ModelRequest、ToolRequest 类型化贯穿、AgentContext 只读快照）

## 问题

Agent 运行时有两条多余的复杂度，使 engine 热路径偏厚且难以拆分：

- **双重状态维护**：`AgentStatus` 的 `WAITING_MODEL`、`WAITING_TOOL`、`WAITING_CHILDREN` 是 activities/agents 表的可推导投影，却被持久化并由每条决策手工维护。状态漂移需要在 `recover_interrupted` 中修复，还残留 `WAITING_EFFECT` 历史迁移。状态枚举与 SQL 中 62 处裸字符串没有单一事实来源。
- **双重决策类型**：`AgentDecision`（handler 输出）与 `Command` 六个类（授权后指令）字段一一对应但各自持有一套 dict 载荷；`apply_decision` 以 isinstance 分派六种指令，为工具请求手工拼 session_id、为委派手工解析默认 profile，并在事务外重复查询。

## 决定

### 1. 删除 Command 层，授权与执行边界改为直接消费 AgentDecision

- 删除 `src/engine/commands.py` 的全部六个 Command 类。
- `store.apply_decision(message, agent, decision, *, state_patch, limits, priority)` 直接接收类型化 `AgentDecision`：
  - model 分支：持久化 `decision.model_request.to_dict()`；摘要 `model.requested`。
  - tool 分支：持久化 `{**decision.tool_request.to_dict(), "session_id": task_row["session_id"], "request_id": <新生成>}`；`session_id` 在事务内从已读取的 task 行解析，删除运行时对 `get_task` 的额外查询。
  - delegate 分支：在事务内以 `limits.worker_profile` 解析 `DelegationRequest.profile_id` 的默认值（授权已校验 child_profiles 成员关系，解析规则与授权侧一致）。
  - wait 分支：原子校验「存在非终态 children 或 pending child reports」，不再由运行时在事务外做两次查询；校验失败在事务内抛出。
  - 因果事件载荷改为 `decision.to_dict()`（契约新增，序列化全部类型化字段），摘要由 `_decision_summary(decision)` 统一推导。
- 运行时授权函数 `_apply_model_request`、`_apply_tool_request`、`_apply_delegations` 收敛为纯校验器（只校验、不构造载荷），`apply_authorized_decision` 只负责按决策字段分派校验；校验通过后原样把 `AgentDecision` 交给 store。
- 资源上界校验（预算、委派深度/计数）继续留在 store 事务内，RFC 0203 的边界不变：handler 仍不能直接调用 store。

### 2. AgentStatus 收敛，等待状态改为派生

- `AgentStatus` 收敛为 `READY`、`COMPLETED`、`FAILED`、`CANCELLED`；删除三个 `WAITING_*` 值。
- 等待语义由数据库事实派生，消息接纳矩阵如下（与现行行为等价，且互斥）：
  - `task.started` / `agent.assigned`：Agent 空闲——无非 CANCELLED 的 Activity、无非终态 children、无 pending child reports。
  - `model.completed` / `model.failed`：存在该 Agent 的 model Activity（非 CANCELLED）。Activity 完成并投递消息后仍保留在表中，故门控稳定。
  - `tool.succeeded` / `tool.failed` / `tool.unknown`：存在该 Agent 的 tool Activity（非 CANCELLED）。
  - `child.completed` / `child.failed`：存在非终态 children 或 pending child reports。
- `claim_message` 的接纳条件改写为上述 EXISTS 子查询；`idx_activities_one_active_per_agent` 部分唯一索引保证每 Agent 至多一个活跃 Activity，查询代价可控。
- `apply_decision` 各分支不再维护等待状态：非终态分支统一落到 `READY`，终态分支不变。
- SQL 中的状态字面量统一从 `contracts.agent` 枚举常量生成，删除裸字符串。
- 可观测性：`agent_detail` 投影新增派生字段 `waiting_on`（model/tool/children 列表），供调试与 Dashboard 展示；`AgentInstance.status` 只保存持久化基态。

### 3. Schema 与迁移

- `_SCHEMA_VERSION` 7 → 8；初始化迁移新增：
  `UPDATE agents SET status = 'READY' WHERE status NOT IN ('READY', 'COMPLETED', 'FAILED', 'CANCELLED')`
  该语句同时归一化旧库的 `WAITING_*` 与 `WAITING_EFFECT`，`recover_interrupted` 不再需要状态修复。
- 已归档的 Task JSON 中的 `WAITING_*` 字符串只作展示，不参与状态机解析，无需重写归档。
- 旧版工作区拒绝逻辑、任务预算、审计载荷结构（kind/summary/request 投影）语义不变。

## 结果

- engine 热路径每轮减少一次 `get_task` 查询；wait 校验并入事务；删除一个 121 行模块与 store 的六路 isinstance 分派。
- Agent 状态不再存在第二套需要手工维护的真相；迁移代码清零。
- `runtime.py` 的授权部分变为纯校验器，为后续按职责拆分 `authorize/ingress/state/engine` 铺平道路。
- 不改变任何外部可见行为：消息接纳、租约、幂等、因果记录、资源上界与崩溃恢复语义保持原样。

## 兼容性

- `AgentStatus` 枚举删值属于契约变更：所有写库路径由 migration 归一化，读库路径只接受新枚举值。
- Dashboard、localhost 调试投影只读展示状态字符串，新增 `waiting_on` 字段向后兼容。
