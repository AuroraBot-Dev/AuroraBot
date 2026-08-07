# 0216：记忆引擎——窗口 + 概要（短期）与 mem0（长期）

状态：已接受
日期：2026-08-07
来源：memory 包完全重写决策（langchain 式 summary buffer + mem0 长期记忆）
先决条件：RFC 0202（有界上下文）、RFC 0207（记忆同源）、RFC 0215（embedding role、OpenAI client 导出）

## 问题

现 MemoryService（262 行）只有"滚动摘要 + 事实 + 幂等"，缺两个层次：

1. **短期历史无原始消息窗口**：Agent 只拿到压缩摘要，无法引用最近对话的原文（RFC 0202 以有界摘要取代原始注入，但摘要的信息损失无法回溯）。
2. **长期记忆无语义检索**：durable_facts 只是关键词匹配，无向量/语义能力。

用户决策：短期 = **langchain 式「窗口 + 概要」**（summary buffer memory），长期 = **mem0**（向量语义检索），两者共同构成记忆引擎。

## 决定

### 1. 契约扩展（contracts/memory.py）

```python
@dataclass(frozen=True, slots=True)
class MemoryMessage:
    role: str        # "user" | "assistant"
    content: str
    at: str          # ISO 时间

@dataclass(frozen=True, slots=True)
class MemoryContextSnapshot:
    summary: str = ""                    # 窗口外压缩概要
    window: tuple[MemoryMessage, ...] = ()  # 最近 N 条原始消息
    relevant_facts: tuple[str, ...] = ()   # 长期记忆检索结果

class MemoryStore(Protocol):
    def recall(self, query: MemoryQuery) -> MemoryContextSnapshot: ...
    def remember(self, entry: MemoryEntry) -> bool: ...            # 终态投影（不变）
    def append_turn(self, scope: str, *, role: str, content: str, at: str) -> None: ...  # 每轮窗口追加
```

- `AgentContext.memory` 类型不变（仍 `MemoryContextSnapshot`），engine 组装侧无感。
- 新增 `append_turn`：engine 在每轮决策后调用（窗口消息来自运行态投影）。

### 2. 短期记忆：窗口 + LLM 概要（langchain summary buffer）

- 存储：SQLite 新增 `memory_messages(scope, seq, role, content, at)`；`session_memory` 保留为概要。
- 窗口上限 `max_window`（默认 20 条）：`append_turn` 超出后，把**最旧的 m 条 + 现有概要**交给模型网关浓缩为新概要（LLM 摘要，`fast` role），删除被浓缩的消息。
- 概要生成依赖模型网关——`MemoryService` 构造时注入 `ModelGatewayService`（组合层）。
- `recall`：返回 `summary + window（最近 N 条原文）+ relevant_facts`。

### 3. 长期记忆：mem0

- 引入 `mem0ai` + 本地向量存储（Chroma，数据落 `data/memory`）。
- **embedding 用我们的 embedding role**（mem0 自定义 embedding 函数 → `EmbeddingRole.embed`）。
- 写入：记忆 agent 的 `aur.serv.memory.remember` 同时写短期（窗口/概要）与长期（mem0.add）；终态投影写短期。
- 检索：`recall` 时 `mem0.search(query, user_id=scope)` → `relevant_facts`。
- mem0 作为 `LongTermMemory` 组件，与短期 `ShortTermMemory` 同被 `MemoryService` 组合（记忆同源：一个入口）。

### 4. 组合与渲染

- `aurora` 组合：`ModelGatewayService → MemoryService(gateway, ...)`（摘要 + embedding + mem0）。
- `composer` 的 memory system 消息渲染三层：概要 → 窗口消息 → 长期事实。
- engine：`_pump_turns` 每轮决策后 `memory_store.append_turn(...)`；终态投影 `remember` 不变。

## 结果

- 记忆三层齐备：**窗口**（短期原文，langchain 式）→ **概要**（窗口外压缩，LLM 生成）→ **mem0**（长期语义检索）。
- 记忆 agent 的主动写入同时贯通短期与长期，同源（RFC 0207 不变）。

## 兼容性

- 契约变更：`MemoryContextSnapshot` 增加 `window` 字段（默认空元组，向后兼容）；`MemoryStore` 增加 `append_turn`（engine 侧新增调用点）。
- 依赖新增：`mem0ai`、`chromadb`。
- 存储：`memory.sqlite3` 新增 `memory_messages` 表（Schema 就地扩展，不迁移）。
- mem0 配置可选：未配置 mem0（或依赖不可用）时长期记忆降级为现有 durable_facts 关键词检索。
