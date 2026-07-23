# 0108：三层记忆

状态：已接受
日期：2026-07-23
来源：取代 RFC 0021

## 职责

`src/memory/` 提供基于 mem0 + ChromaDB 的语义记忆读写，以及基于 causal_events 的情景记忆召回。
依赖 `src/contracts`、`src/utils` 以及 `mem0ai`、`chromadb`。

## 三层模型

| 层  | 存储               | 读方式                                                    | 写方式                     |
| --- | ------------------ | --------------------------------------------------------- | -------------------------- |
| L1  | Kernel Mailbox     | 直接拼接在 user prompt 中                                 | 框架自动                   |
| L2  | `causal_events` 表 | `MemoryService.recall_recent_events()` → user prompt 注入 | 框架自动                   |
| L3  | mem0 + ChromaDB    | `MemoryService.search()` → user prompt 注入               | Agent 工具委派 MemoryAgent |

## 读路径：自动注入

PromptComposer 接收可选 `MemoryService` 依赖。每 turn 自动查询 L2 情景事件和
L3 语义事实（使用 `task.root_summary` 作为查询键），结果作为 user prompt 的独立 section 注入。
所有 Agent 共享同一 PromptComposer，因此共享记忆上下文。

## 写路径：Agent 委派

- `aurora.memory.remember`：模型调用时委派给 MemoryAgent
- `aurora.memory.query`：显式深入查询通道
- 大规模查询结果（超过 8 条）时，通过 continuation 实现多轮推理消化

## MemoryAgent

- 实现 `AgentHandler` 协议但不调用模型
- 收到 `task.started` 消息后解析委派指令，直接执行 mem0 读写
- 返回 `Completion`，不产生额外 Token 成本

## MemoryService

公开接口：

- `search(query, limit)` → 语义搜索
- `recall_recent_events(task_id, limit)` → 情景事件召回
- `remember(fact)` → 写入语义记忆
- `forget(fact_id)` → 删除记忆

## 配置

```toml
# config/agents.toml
[[agent]]
id = "builtin.memory"
implementation = "src.agents.memory_agent:MemoryAgent"
model_role = "fast"
capabilities = ["*"]
can_delegate = false

# config/aurora.toml
[runtime.agents]
memory_agent_profile = "builtin.memory"
```

未配置 Memory Agent 时，`aurora.memory.query/remember` 返回 `memory.unavailable`。
记忆数据目录：`data/memory/`（ChromaDB 向量 + mem0 history.db）。

## 约束

- MemoryService 不直接调用模型或 Platform
- 写路径必须通过 Agent 委派，保留因果追踪
- `memory_agent_profile` 不配置时不自动启用记忆
