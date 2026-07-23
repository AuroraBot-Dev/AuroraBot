# 0102：Kernel 运行时

状态：已接受
日期：2026-07-23
来源：取代 RFC 0012（Kernel 部分）；整合自 RFC 0001、0014、0020

## 职责

`src/kernel/` 负责 Task/Agent 生命周期、邮箱、Activity 调度、因果事件和 SQLite 持久化。
不决定认知内容，不直接执行平台效果，不依赖 prompt、AI、Platform 或 localhost。

## 核心实体

### Task

- 每个外部根 AMP 或 `system.tick` 创建一个 Task 和根 Gate Agent
- Task 拥有模型调用数、工具调用数、持续时间的共享预算
- 状态：`PENDING` → `ACTIVE` → `COMPLETED` / `CANCELLED` / `ERROR`
- 根 Task 结束时取消整棵监督树
- 终态 Task 导出规范 JSON 到 `archive/tasks/`

### Agent

- 所有 Agent 同构：同一生命周期与消息协议
- 每个 Agent 同时最多执行一个 turn；不同 Agent 可并行
- Agent 可递归创建子 Agent；子级完成/失败后回报父级
- 子 Agent 不得请求 terminal 效果（该概念已被 RFC 0018 移除——所有 Tool 结果均恢复请求 Agent，`complete_task=true` 控制 Task/子 Agent 完成）

### 邮箱

- Agent 一次消费一条持久化邮箱消息
- 每条消息绑定目标 agent_id，包含类型、payload、causation_id
- 消息领取使用租约；崩溃前未提交的消息可重新领取
- 新产物（模型完成、Tool 回执、子级回报）以新邮箱消息恢复原 Agent

### Activity

- Agent 返回 Decision 后，Kernel 在事务中创建 Activity
- Activity 类型：`model`（模型请求）、`tool`（工具请求）
- 由异步 worker 执行后，结果以新邮箱消息恢复原 Agent
- 每个 Agent 最多一个活跃 Activity

### 因果关系

- `causal_events` 表记录所有事实：AMP 接管、Agent 决策、Activity 结果、状态迁移
- 每条事件可追溯到根输入、产生节点和单一因果父级
- 因果事实是不可变审计记录，不用于传递实时状态

## BrainContext

Runtime 维护只读 `BrainContextSnapshot`：

- SOUL 基底人格哈希
- 所有活跃 Task 和 Agent 的确定性简讯
- 尚未归属 Agent 的情境事件（Situation）

部署被视为同一可信人格域，活动内容摘要不按 session 隔离。
不得包含密钥、Provider 私有对象、隐藏推理或未规范化附件。

## 持久化

- 运行态：`process/runtime.sqlite3`，使用 WAL 模式
- 一次 Agent turn 必须原子确认 revision、完成输入消息、更新状态并写入新消息和 Activity
- 重启恢复：已开始的 model/tool Activity 视执行器是否有幂等账本而定——实现恢复的执行器按账本裁决，未实现恢复的返回 unknown
- 外部入口：AMP 仍使用临时文件加原子改名投递到 `inbox/`

## 调度与自主

- Kernel 自身不计算或发射自主 tick
- localhost Runtime 轮询 inbox 和就绪消息，调用 `kernel.pump(max_turns)` 推进
- `system.tick` 由 Clock MCP App 发送，经统一 AMP ingress 进入
- 非 tick 外部活动到来时取消进行中的 autonomous Task
- 自主日模型调用和 token 上限由 localhost `AutonomyQuota` 持久化执行

## 预算

每个 Task 共享预算（所有 Agent 原子扣减）：

| 限制项             | 说明               |
| ------------------ | ------------------ |
| `max_model_calls`  | 最多模型调用数     |
| `max_tool_calls`   | 最多工具调用数     |
| `max_duration`     | 最长持续时间       |
| `max_depth`        | 最大委派深度       |
| `max_children`     | 最大子 Agent 数    |
| `max_total_agents` | Task 内总 Agent 数 |

## 约束

- Kernel 不导入 AI、Platform、prompt 或 localhost
- 不直接操作平台私有对象或协议
- 配置快照注入后不可变
