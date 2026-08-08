# 0210：最小 engine 重写——单一存储、无租约、BaseAgent 基类

状态：已接受
日期：2026-08-07
来源：RFC 0208 层级重定性的执行决定；全量重写 engine，允许改变 Schema 与存储语义；取代 RFC 0201 的 JSON 归档/JSONL 会话日志、RFC 0202 的 admit 留存细节
先决条件：RFC 0207（记忆 agent）、RFC 0209（Agent 全同构、入口 triage agent）

## 问题

engine 现有实现 3301 行，其中约 1500 行是历史累积与投机复杂度：

- **三套持久化**：SQLite 运行态 + JSON 终态归档 + JSONL 会话日志，各自维护（archive/prune/反查/maintain_storage），每次 pump 都有归档开销。
- **双租约 + CAS**：mailbox 与 activities 各自的 lease_until、agents.revision 乐观锁、expire_tasks、recover_interrupted、recover_pending——为多进程/超时场景设计，而运行时明确规定单进程单所有者。
- **审计重复**：causal_events 存完整 `decision.to_dict()`，activities 再存完整请求载荷。
- **中间层透传**：AgentEngine → EngineState（大量透传查询）→ SQLiteRuntimeStore（7 个 Mixin）。
- **Agent 逻辑类无共享基类**：TriageAgent 与 ToolAgent 只共享 AgentHandler Protocol，模型请求装配、工具定义收集、能力调度等逻辑重复。

## 决定

### 1. 并发模型：单进程 asyncio 独占，删除全部租约

- engine 明确单进程单事件循环：turn 的 handler 是同步纯函数（只构造决策），模型/工具调用是 async——**不需要线程池执行 handler，不需要 lease_until、revision、CAS**。
- claim 退化为原子 UPDATE（单写者无竞争）：`UPDATE messages SET status='PROCESSING' WHERE message_id = (SELECT ... LIMIT 1)`。
- 崩溃恢复只做一件事：启动时 `PROCESSING → PENDING`（消息）、中断的 model Activity 标 ERROR 并投递 `model.failed`、工具 Activity 保留待恢复。
- 删除：`ThreadPoolExecutor`×3、`_store_call`/`_blocking_call`、expire_tasks 租约检查、lease_seconds 配置；`EngineState` 中间层合并进 `AgentEngine`。
- memory 的同步 SQLite 调用保留 `asyncio.to_thread` 包装。

### 2. 存储形态：单一 SQLite 即归档

- **删除 JSON 终态归档与 JSONL 会话日志**：终态 Task 留在 SQLite（终态行即档案），由 `causal_events` 提供可读性；会话日志按需由 ops 从 causal_events 导出。取代 RFC 0201 的"先归档后清理"与 AGENTS.md 的 JSONL 约定。
- 清理策略：终态行保留，可配置 TTL 由 ops 命令触发删除（不做热路径归档）。
- 外部 AMP 文件摄入保留（platform 写 JSON → engine 读），但处理完即移入 rejected/duplicate 分类目录（现状不变）。**该条款已被 RFC 0219 废弃**：inbox/archive 文件投递箱移除，摄入统一经 submit_amp SQLite 直连。
- 审计去重：`causal_events.payload_json` 只存轻量摘要（决策种类、摘要文本、关联 ID），不再存完整请求；activities 仍存执行所需完整请求。

### 3. Schema v9（自即日起数据库必须考虑迁移）

六表结构保留（tasks/agents/messages/activities/causal_events/inbox_events），删除列：

- messages：删 `lease_until`、`attempts`、`available_at`（保留优先级排序与 created_at）；状态 PENDING/PROCESSING/COMPLETED/ERROR。
- activities：删 `lease_until`；状态 PENDING/PROCESSING/COMPLETED/ERROR/CANCELLED；`idempotency_key` 保留（工具幂等回执）。
- agents：删 `revision`（单进程无并发写）。
- causal_events：删 `external_message_id`（幂等由 correlation_id 承担）、`causation_id` 保留。
- tasks：删 `audience_ref`（未使用）；`root_message_id` 语义改为批次 ID（入口 triage 使用），保留。
- 原"不接受旧库迁移"政策撤销：v1–v8 旧库按版本化迁移序列升级到 v9，迁移步骤重建自
  历史演化档案（`src/engine/store/migration/`，见 RFC 0217 §5）；代码路径只访问 v9
  形状、不兼容旧版本列，迁移在启动时单事务完成、任一版本步骤失败整体回滚。
- 旧**进程目录**形态（records/episodes JSON）仍由 `reject_active_legacy_workspace`
  拒绝，与 SQLite 版本迁移无关。

### 4. 运行时形态

```
pump():
  1. ingest          → Inbox 文件 + 内存队列 → inbox_events（文件通道已被 0219 废弃）
  2. triage batches  → 到期批次创建入口 triage Task（同 RFC 0209）
  3. claim messages  → 原子 UPDATE 领取，同步执行 handler（事件循环内）
  4. apply decision  → 8 分支状态机（model/tool/delegate/complete/wait/defer/discard/fail）
  5. dispatch I/O    → async 派发 model/tool activities（asyncio 任务簿仅用于 shutdown 等待）
  6. memory 投影     → to_thread 调用 MemoryService
  7. 终态留存        → 无归档步骤；仅记录 task.finished 到 causal_events
```

- 模型派发、工具派发保持后台 asyncio 任务，但删除任务簿复杂度：用一个 `asyncio.Task` 引用 + shutdown 时取消即可（现有 `_model_activity_tasks` 字典删除）。

### 5. BaseAgent 基类（逻辑同构的代码化）

- 新增 `src/agents/base.py`：`BaseAgent` 抽象基类，所有 Agent 逻辑类继承。
- 共享职责：composer 装配、`ModelRequest` 构造（含 tools/output_schema/continuation）、工具定义收集与唯一性检查、Capability 调度、决策工厂方法（`_delegate`/`_complete`/`_fail`/`_wait`/`_defer`/`_discard`）。
- `ToolAgent(BaseAgent)`：工具链状态机（现 handler.py 逻辑迁移）。
- `TriageAgent(BaseAgent)`：结构化判断 + fail-open（现 triage.py 逻辑迁移）。
- 记忆/委派/等待/朗读 Capability 的 Protocol 不变。

### 6. 保留的语义（不可漂移）

- AMP → 防抖 → 批次 → 入口 triage agent → 委派链 → 决策 → 模型/工具 → 记忆投影 全链路（RFC 0202/0207/0209）。
- Agent 三元组实例化、`triage_control` 门控、`!` 排除语义、fail-open、defer/discard 的批次结算。
- 记忆同源（唯一 MemoryService）、工具幂等回执、模型/工具预算、深度/数量限制。
- 输出流（OutputStream）与 /status /task /agent 查询接口语义。

## 结果

- engine 预计从 3301 行降至约 1800-2000 行（合并中间层、删除归档/租约/JSONL）。
- 单文件 runtime 恢复 500 行以内；store 精简为 3 个 Mixin（runtime/queue/inbox）。
- 崩溃恢复路径从"多机制组合"降为"启动一条 UPDATE"。
- Agent 逻辑同构有明确的代码载体（BaseAgent）。

## 兼容性

- Schema v1–v8 旧库按版本序列迁移至 v9（RFC 0217 §5）；旧进程目录形态（records/episodes）仍需重建。
- ops 命令与调试 API：`/task`、`/agent` 改读 SQLite 终态行（删除归档反查路径）；`/log` 会话导出改为 causal_events 投影。
- 外部契约（AMP、配置、平台 Tool 协议、MemoryStore）不变。
- 测试：删除租约/归档/JSONL 测试；迁移测试改为 v2/v7 样本库升级到 v9 的断言；pump 流程测试按语义重写；contracts/config/prompt/ai/platform/memory 测试保留。
