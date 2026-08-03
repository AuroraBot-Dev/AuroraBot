# 0201：有界上下文与运行态留存

状态：已接受
日期：2026-07-29
来源：补充 RFC 0200 的模型上下文、平台事件归一化与运行数据生命周期

## 问题

RFC 0200 确立了 Agent 中心热路径，但没有规定模型上下文和终态运行数据的上界。现行实现因此出现：

- 最近对话跨 `session_id` 全局混入，短时通知也被当作对话记忆；
- 工具说明同时出现在 prompt 正文和模型 `tools` 参数中；
- 每个终态 Task 同时完整保留于 SQLite 与 JSON 归档，WAL 继续增长；
- MCP Tool 的文本、结构化内容和原始 content 可表达同一结果，却被一并传入延续状态；
- 不可读的哈希 Tool 别名容易被模型轻微改写，造成有 Tool call 却没有对应 Tool result 的失败续轮。

这些问题会放大第二轮及后续轮次的输入、占用模型并发槽，并使少量 Task 产生不成比例的磁盘占用。

## 决定

### 会话作用域和硬上界

- 自动注入的最近对话严格按 `Task.session_id` 召回，不跨 Console、Dashboard、私聊或群聊会话混合。
- `MemoryQuery` 同时声明条数和字符预算；Memory 实现必须先选择最新记录，再在预算内返回，不能只依赖条数上限。
- 当前默认上界为最近 4 轮、合计 4000 个字符。语义记忆仍可使用全局用户作用域，但不得改变最近对话的会话隔离。
- Prompt composer 不在正文重复渲染已经通过模型 `tools` 参数提供的 Tool 描述和 schema。
- 全局 Activity 只提供有界、去重的 Task 摘要投影；当前 Agent、当前 Task 和完整 Agent 列表不重复注入。

### 平台瞬时事件

- Platform/App 在生成 AMP 前可以按显式 TOML 配置丢弃没有持续语义的供应商瞬时事件。
- Aurora-QQ 默认丢弃 `qq.notice.notify.input_status`。消息、请求和其他通知仍按原契约进入 AMP。
- 该过滤属于外部生态归一化，不替 Agent 改写已经进入 engine 的事实。

### Tool 传输

- 模型 Tool 别名必须确定、可读并满足 Provider 标识符约束；仅在截断或碰撞时附加短摘要。
- MCP Tool 成功结果使用单一规范表示：优先结构化内容，其次可解析 JSON 文本，最后才是纯文本。不得同时保留等价的 `content`、`text` 和 `structured_content`。
- Provider 可以在一次响应中返回多个 Tool call。Agent 不得只执行第一项或为其余项伪造 rejected receipt；
  所有调用及其结果都必须恰好一次进入可恢复执行与同一 continuation。具体调度不限制模型的调用组合，遵循
  RFC 0203。
- 模型 continuation 和完整 Tool schema 是活跃 Activity 的恢复数据，不是长期记忆。Task 归档可以把 Tool 定义压缩为名称列表，并移除结果中的 continuation 重放副本，但必须保留 Tool call、Tool result、文本、用量、诊断和因果元数据。

### 热库与归档生命周期

- SQLite 只保存活跃 Task、尚未完成的恢复状态和外部消息幂等墓碑。
- 终态 Task 必须先原子写入 `archive/tasks/<task_id>.json`，再从 `tasks`、`agents`、`mailbox`、`activities` 和详细 `causal_events` 中清除。
- 带 `external_message_id` 的因果记录在清除时压缩为无 Task 归属的墓碑，继续保证外部 AMP 和 Tool receipt 幂等。
- `task_detail()` 和 `agent_detail()` 对已清除对象从 JSON 归档回读，保持 localhost 检查契约。
- engine 使用增量 auto-vacuum、受限 WAL 和 checkpoint 回收已释放页；一次性 schema 迁移可以重建旧数据库以启用该策略。
- models.dev 目录属于 `src.ai` 的共享能力缓存，不计入单 Task 归档；缓存实现使用 gzip 且只保留当前有效快照。

## 结果

模型首轮上下文不会随其他会话或通知风暴增长，后续 Tool 轮只携带必要的无状态 continuation。终态 Task 的详细审计数据只存在于归档，热库保留量与当前并发工作而不是历史 Task 总数相关。平台噪声不会消耗 Agent turn 或模型并发。
