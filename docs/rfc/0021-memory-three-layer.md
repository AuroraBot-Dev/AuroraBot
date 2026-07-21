# RFC 0021：三层记忆与自动召回

状态：已接受
日期：2026-07-22

## 背景

RFC 0012 预留了 `memory_agent_profile` 和 Memory Agent 委派路径，但记忆实现被推迟。当前代码库只包含占位合约
（`MemoryQuery`、`MemoryResult`、`MemoryProposal`、`MemoryFailure`），`mem0ai` 和 `chromadb` 已在依赖中但
未被使用。旧 `src/brain/memory/` 的三级记忆（工作/情景/语义）在重构中被移除。

## 目标

1. 在 `src/memory/` 包中提供基于 mem0 + ChromaDB 的语义记忆读写和基于 causal_events 的情景记忆召回。
2. PromptComposer 在每个 Agent turn 自动注入 L2 情景事件和 L3 语义事实；`aurora.memory.query` 工具保留为
   显式深入查询通道。
3. 写路径走同构 Agent 委派（`builtin.memory` → `MemoryAgent`），保留因果追踪。
4. 大规模记忆召回时通过延续轮次（continuation）实现长思考。

## 决策

### 三层记忆模型

| 层 | 存储 | 读方式 | 写方式 |
|---|------|--------|--------|
| L1 工作记忆 | Kernel Mailbox/Agent 回合内的消息流 | 直接拼接在 user prompt 中 | 框架自动 |
| L2 情景记忆 | `causal_events` 表（SQLite） | `MemoryService.recall_recent_events()` → user prompt 注入 | 框架自动（内核因果事件） |
| L3 语义记忆 | mem0 + ChromaDB | `MemoryService.search()` → user prompt 注入 | Agent 工具 `aurora.memory.remember` → 委派 MemoryAgent |

### 读路径：自动注入，不走 Agent 循环

PromptComposer 接收一个可选的 `MemoryService` 依赖。在 `request_document()` 中，每 turn 自动查询
L2 情景事件和 L3 语义事实（使用 `task.root_summary` 作为查询键），将结果作为 user prompt 的独立 section
注入。所有 Agent（根和子）走同一个 PromptComposer，因此共享记忆上下文。

### 写路径：Agent 委派

新增 `aurora.memory.remember` 工具，模型调用时委派给 `MemoryAgent`。`MemoryAgent` 不调用模型，直接
操作 mem0 并返回结果。

### MemoryAgent 是纯服务 Agent

`MemoryAgent` 实现 `AgentHandler` 协议但不调用模型——收到 `task.started` 消息后解析委派指令，
直接执行 mem0 读写并返回 `Completion`。因此它不产生额外 Token 成本。

### 长思考：延续轮次

当 `aurora.memory.query` 返回超过 8 条结果时，`ToolAgent._handle_memory_query` 构造
`model_request`（continuation）而非立即 completion，让模型多轮推理消化大量记忆后再决定行动。

## 模块边界

```
src/memory/           新包：记忆读写的直接服务层
  └─ 依赖 src/contracts/, src/utils/, mem0ai, chromadb

src/agents/memory_agent.py  新 handler：MemoryAgent
  └─ 依赖 src/contracts/, src/memory/

src/prompt/composer.py      修改：注入 MemoryService
  └─ 可选依赖 src/memory/（通过可选导入构造器参数）

config/agents.toml          新增 builtin.memory profile
config/prompts/agents/memory.md  新增记忆 Agent 提示词片段
```

依赖方向符合：`utils/contracts ← memory ← agents ← ...`

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

记忆数据目录：`data/memory/`（ChromaDB 向量 + mem0 history.db）。
