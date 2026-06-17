现在我已全面了解该项目，以下是审查报告。

---

# AuroraBot 项目代码审查报告

## 项目概观

AuroraBot v0.4.0 是一个基于 NoneBot2 + LiteLLM 的内驱式自主智能体框架，采用 **文件事件驱动的认知拓扑电路**（FileEventBus → Node → FileUpdate）架构。核心包含：AI 模型网关、三级记忆系统（L1 工作 / L2 情景 / L3 语义）、认知管线（Internalizer / Externalizer）、事件总线和应用平台层。整体架构设计思路上有原创性，代码风格一致性好，中文注释详尽。

---

## 一、Critical（必须修复）

### 1. `CostTracker.summary()` 非异步安全 — 迭代时未持锁

**文件:** `src/brain/ai/gateway.py:123-144`

```python
def summary(self) -> dict:
    total = 0.0
    by_role: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    for r in self._records:   # ← 未持有 _lock，与 add() 并发时可能崩溃
```

`add()` 通过 `async with self._lock` 修改 `_records`，但 `summary()` 直接遍历 `_records` 且不持锁。若在遍历过程中另一协程 `await cost_tracker.add()` 修改了列表，会触发 `RuntimeError: dictionary changed size during iteration`。

**修复:** `summary()` 内部也应 `async with self._lock`，或改为返回 snapshot。

---

### 2. `TaskManager._tasks` 竞态条件

**文件:** `src/brain/ai/gateway.py:192-197`

```python
def create_task(self, coro) -> GenerationTask:
    task_id = uuid.uuid4().hex[:8]
    task = asyncio.create_task(coro)
    self._tasks[task_id] = task          # (1)
    task.add_done_callback(lambda _t: self._tasks.pop(task_id, None))  # (2)
    return GenerationTask(task_id, task)
```

虽然 asyncio 是单线程，但 `task.add_done_callback` 注册的回调可能在下一轮事件循环即刻触发（若 coro 立即完成），此时 `return GenerationTask(...)` 尚未返回，`task_id` 已被从 dict 中移除——目前只影响可读性（pop 了刚放进去的 key），不致命但脆弱。极端情况下若 `DoneCallback` 中未来增加了更多逻辑可能出问题。

**修复:** 在 `return` 之后再注册回调，或确保回调幂等。

---

### 3. `DecoratorFactory.exception()` — 日志记录时机错误（bug）

**文件:** `src/utils/log_utils.py:173-193`

```python
def exception(self, message_template: str):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            ...
            self._logger.exception(message_template.format(...))  # ← 函数执行前就 log！
            return func(*args, **kwargs)                            # ← 然后才执行函数
```

`logger.exception()` 用于记录**已发生**的异常并附带 traceback。此处函数尚未执行，没有异常发生，`logger.exception()` 会记录一条 `NoneType: None` 的无意义 traceback。这明显是逻辑 bug。

**修复:**

```python
def wrapper(*args, **kwargs):
    ...
    try:
        return func(*args, **kwargs)
    except Exception:
        self._logger.exception(message_template.format(...))
        raise
```

---

## 二、Important（应该修复）

### 4. `_bootstrap_heartbeat` 每次启动都覆盖 tick.json

**文件:** `src/brain/kernel/circuit.py:107-131`

电路每次 `start()` 都会无条件写入 `tick.json`（`tick_id: "bootstrap"`），不检查文件是否已存在。这会覆盖上一次运行时 HeartbeatGenerator 写入的状态，重启后丢失 tick 序列连续性。

**修复:** 启动前检查文件是否已存在，仅当不存在时写入初始 bootstrap 脉冲。

---

### 5. 语义记忆提取的 fire-and-forget task 无异常处理

**文件:** `src/brain/memory/__init__.py:72`

```python
asyncio.create_task(self._extract_async(text, user_id))  # noqa: RUF006
```

虽然 `_extract_async` 内部有 `try/except`，但若未捕获的异常（如 `asyncio.CancelledError` 或未来代码变更）会导致 task 静默失败并被 GC。更稳妥的做法是保存 task 引用并添加通用 done callback 记录异常。

---

### 6. `__init__` 中同步 I/O 阻塞事件循环

**文件:**

- `src/brain/nodes/agents/polaris_agent.py:72-97` — `_init_data()` 读写 `history.json`
- `src/brain/nodes/self_stream.py:67-82` — `_init()` 读写 `now.md` 和 `state.md`
- `src/brain/memory/semantic.py` — `extract_and_store` → `mem0.add`（可能涉及 LLM 调用）

这些操作在构造函数（同步上下文）中执行，且 PolarisAgent 的 `_init_data` 可能调用 `logger.exception()`，这些都不应在 `__init__` 中发生。

**修复:** 考虑工厂函数 `async def create_polaris_agent(...)` 或将初始化移至 `async def start()`。

---

### 7. `UnifiedMemoryManager.retrieve_context()` 同步阻塞

**文件:** `src/brain/memory/__init__.py:84-100`

`semantic.search_facts()` 内部调用 `self.mem0.search()`，这是同步 ChromaDB 向量搜索，可能耗时数百毫秒。`retrieve_context` 是同步方法，在 asyncio 上下文中调用会阻塞事件循环。

PolarisAgent 通过 `loop.run_in_executor(None, ...)` 将 `_build_advanced_memory_text` 放入线程池来解决——这是正确的做法。但 `retrieve_context` 本身的 API 设计是同步的，容易误用。

**修复:** 将 `retrieve_context` 改为 `async`，或至少将 L3 搜索包装为异步。

---

### 8. `RUN_MODE` 字符串匹配脆弱

**文件:** `src/brain/runtime.py:93-96`

```python
if Config.RUN_MODE in ["app", "application", "dev", "prod"]:
    ...
if Config.RUN_MODE in ["agent", "core", "dev", "prod"]:
```

多用字符串列表做成员检查，新增 mode 时需在两处同步更新，容易遗漏。

**修复:** 改用位掩码或集合运算，例如 `RUN_MODE_APP = {"app", "application", "dev", "prod"}` 作为模块常量。

---

## 三、Suggestions（建议改进）

### 9. `_build_commands_text` 三处重复

`Externalizer._build_commands_text()`、`Internalizer._build_commands_text()` 和 `PolarisAgent._build_commands_text()` 实现几乎完全相同（~20行），违反 DRY 原则。

**建议:** 抽取为 `src/brain/nodes/utils.py` 或 `ApplicationHost` 上的方法。

---

### 10. 代理 (Proxy) 模式三处重复

`_GatewayProxy` / `_MemoryManagerProxy` / `_AppHostProxy` 的核心逻辑完全相同（`__getattr__` 委托到 `get_xxx()`）。可以用一个泛型 `_LazyProxy(getter)` 消除重复。

---

### 11. `Config.ensure_dirs()` 在模块加载时执行

**文件:** `src/config.py:90`

```python
Config.ensure_dirs()
```

模块级副作用：import `config` 就会创建目录。在某些只读环境或测试环境中可能导致意外失败。

**建议:** 移至 `start_runtime` 或显式的 `init()` 调用。

---

### 12. `_default_topology` 按名称排序 — 顺序不可控

**文件:** `src/brain/kernel/node_factory.py:118`

```python
return [{"id": name, "type": name} for name in sorted(NODE_REGISTRY)]
```

节点启动顺序依赖名称的字典序，而电路中的节点之间可能有隐式的依赖关系。默认顺序应与 cognitive pipeline 的逻辑流保持一致。

**建议:** 使用显式的优先级字段或保留注册顺序。

---

### 13. `parse_llm_json` 递归可能无限循环

**文件:** `src/utils/json_utils.py:58-61`

```python
fixed = _fix_json_multiline(text)
if fixed != text:
    return parse_llm_json(fixed)  # 递归
```

如果 `_fix_json_multiline` 产生的新文本与原文本不同但再次通过同样流程又回到原文本，会出现无限递归。

**建议:** 加递归深度限制（如 `_depth` 参数，默认 3）。

---

### 14. `_safe_cost` / `_safe_cost_per_token` 中 `completion_cost` 可能触发网络请求

**文件:** `src/brain/ai/gateway.py:246-279`

`litellm.completion_cost()` 和 `litellm.cost_per_token()` 在某些情况下会发起 HTTP 请求获取定价数据，但在流式响应的热路径上同步调用（`_safe_cost` 是 async 但内部调用同步 `completion_cost`），可能导致事件循环阻塞。

**建议:** 将费用计算放入 `run_in_executor`，或全部走 `models.dev` fallback 路径。

---

## 四、Architecture & Refactoring（架构与重构相关）

> 以下为 MCP 化改造评估过程中发现的结构性问题，与代码缺陷无关，但涉及架构演进的痛点。

### 15. 文本 JSON 解析是认知管线的脆弱环节

**涉及文件:** `src/brain/nodes/agents/externalizer.py:191-225`、`src/utils/json_utils.py`

当前 Externalizer 的 LLM 输出到命令执行的路径为：

```
LLM 文本输出
  → _parse_actions(JSON 正则提取)
  → parse_llm_json(JSON 修复递归)
  → safe_parse_json_object(最后兜底)
  → _adapt_plain_text(纯文本兜底)
  → command_dispatcher 再解析一次
  → host.invoke_command
```

每一步都可能失败，且多层 fallback 增加了复杂度和不可预测性。`parse_llm_json` 的递归修复（#13）是这一模式脆弱的体现。

**影响:** 即使 LLM 输出了语义正确的动作，也有可能因 JSON 格式问题被丢弃，导致 AuroraBot "想做但说不清"。当前实践中 Externalizer 使用 `temperature=0.0` 缓解此问题，但 temperature 不应被结构性缺陷绑架。

**建议:** 引入 LLM 原生 function calling（MCP 化或直接使用 OpenAI tool_calls），让 LLM 直接输出结构化 `tool_calls`，彻底消除文本 JSON 解析链路。详见 `docs/reports/app-platform-mcp-migration.md`。

---

### 16. Externalizer 与 command_dispatcher 存在双重解析

**涉及文件:**

- `src/brain/nodes/agents/externalizer.py:120-135`（写入 `act_*.json` 时构造 payload）
- `src/brain/nodes/routers/command_dispatcher.py:43-97`（读取 `act_*.json` 时兼容新旧两种格式）

Externalizer 已经把动作解析为 `{"command": "...", "params": {...}}` 结构，但写入 action_queue 后又由 command_dispatcher 再解析一次。command_dispatcher 还需兼容两种格式（旧版顶层字段 / 新版 envelope+payload），并自行处理 `raw_response` fallback。

**影响:** 两次解析加重了管线的延迟和出错概率，且 command_dispatcher 的格式兼容逻辑无法被 Externalizer 复用。

**建议:** 如果保持文本 JSON 模式，将 command_dispatcher 的解析逻辑上移到 Externalizer，action_queue 文件直接存储已标准化的 CommandSpec，command_dispatcher 只做 `host.invoke_command()`。如果 MCP 化，command_dispatcher 节点可直接移除——LLM 的 tool_calls 由 MCP Client 直接执行。

---

### 17. `_build_commands_text` 三处独立实现且语义不同

**涉及文件:**

- `src/brain/nodes/agents/internalizer.py:189-207`
- `src/brain/nodes/agents/externalizer.py:203-226`
- `src/brain/nodes/agents/polaris_agent.py`（~20 行）

三处实现虽结构相似，但格式细节不同（Internalizer 用 markdown 列表，Externalizer 用 JSON 示例段落，PolarisAgent 又是一种变体）。这意味着同样的工具列表以三种形式注入 LLM context，LLM 需要适应三种不同的格式。

**影响:** 维护成本高，且格式一致性问题可能导致 LLM 在不同节点对同一工具的理解偏差。

**建议:** 统一由 `ApplicationHost.build_commands_context()` 生成单一种格式，或由 MCP client 提供标准化的 tool schema。

---

### 18. EventBridge 轮询间隙造成延迟

**文件:** `src/brain/nodes/event_bridge.py:45-72`

```python
await asyncio.wait_for(stop_event.wait(), timeout=max(0.05, interval))
```

EventBridge 以定时轮询方式 drain ApplicationHost 的事件队列，默认间隔 1.5s。这意味着外部 QQ 消息到达后，在最坏情况下需等待 1.5s 才进入认知管线。在低负载时此延迟可接受，但在高并发场景下可能积累。

**影响:** 端到端延迟的波动上限为 `interval` 秒，不致命但值得记录。

**建议:** 引入 `asyncio.Event` 唤醒机制——当 `host.emit_event()` 时同时设置一个 `_event_pending` 事件，EventBridge 改为 `asyncio.wait([stop_event, event_pending], timeout=interval)`。

---

### 19. FileEventBus 写锁是全局 asyncio.Lock，不支持终结语义

**文件:** `src/brain/kernel/event_bus.py:99-101`

```python
def _get_lock(self, path_key: str) -> asyncio.Lock:
    if path_key not in self._file_locks:
        self._file_locks[path_key] = asyncio.Lock()
    return self._file_locks[path_key]
```

当前每个文件路径只有一把 `asyncio.Lock`，没有读/写区分、没有归档终结语义。如果未来引入文件归档（`move_to_done` 删除源文件）时存在并发读，会出现读已删除文件的风险。详见 `docs/reports/kernel-fs-lock-system.md` 中设计的"两阶段门闩"模式。

**建议:** 如果引入文件归档机制，将 `_file_locks` 从 `asyncio.Lock` 升级为 `TerminableSharedLock`（实现 OPEN/CLOSING/ARCHIVED 三态）。当前系统通过文件名约定（`done/` 子目录 + `move_to_done` rename）避免了部分竞态，但 rename 在跨文件系统时不保证原子性。

---

## 总结

| 严重级别     | 数量 | 关键主题                                                            |
| ------------ | ---- | ------------------------------------------------------------------- |
| Critical     | 3    | 并发安全 (CostTracker, TaskManager)、日志 bug (exception decorator) |
| Important    | 5    | 启动行为、事件循环阻塞、fire-and-forget 安全                        |
| Suggestions  | 6    | 代码重复、模块副作用、脆弱排序                                      |
| Architecture | 5    | JSON 解析脆弱、双重解析、命令文本重复、轮询延迟、文件锁语义         |

**整体评价:** 项目架构设计有明确的认知科学隐喻（两池 + 转义者），事件驱动 + 文件持久化的模式使得状态可追溯、可回滚。代码整体质量中上，lint 规则配置全面（ruff + pyright），但并发安全（asyncio + 共享状态）和阻塞 I/O 方面存在一些需要修复的问题。测试覆盖看起来不错（13 个测试文件），建议补上针对并发场景的压力测试。

架构层面，当前认知管线的最大痛点是 LLM 文本输出 → JSON 解析 → 命令派发的脆弱链路。MCP 化改造可系统性解决该问题（详见 `docs/reports/app-platform-mcp-migration.md`）。
