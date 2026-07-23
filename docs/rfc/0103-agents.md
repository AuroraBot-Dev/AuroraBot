# 0103：Agent Handler 与能力

状态：已接受
日期：2026-07-23
来源：取代 RFC 0012（Agent 部分）、RFC 0022；整合自 RFC 0004、0018

## 职责

`src/agents/` 实现同构 Agent handler。每个 handler 只读取 `AgentContext` 并返回 `AgentDecision`；
不得直接写运行态、调用 Provider、调用 Platform client 或执行外部效果。

## AgentHandler 协议

```python
class AgentHandler(Protocol):
    async def handle(self, context: AgentContext) -> AgentDecision: ...
```

已注册 handler 在 `agents.toml` 中按 profile ID 声明实现路径（如 `src.agents.tool_agent:ToolAgent`）。

## 内建 Agent

### ToolAgent（`builtin.gate` / `builtin.worker`）

模型驱动的认知 Agent。核心流程：

1. `task.started` 或邮箱消息到达 → `_request_model`：装配能力工具定义 + 外部工具 → 返回 `model_request`
2. `model.completed` → `_handle_model_result`：遍历注册的 Capability，命中则返回其 decision；未命中则匹配外部 CapabilityDescriptor
3. `tool.*` → `_resume_tool`：构造 continuation 或触发新一轮推理
4. 模型纯文本 completion → 保持 `completion`（不隐式改写成 Tool 调用）

ToolAgent 不包含对 delegate、wait、claim、memory 的硬编码分支——全部通过 Capability 协议 dispatch。

### MemoryAgent（`builtin.memory`）

纯服务 Agent：不调用模型，直接执行 mem0 读写并返回 `completion`。

## Capability 协议

内建能力各自为一个 Capability 类，位于 `src/agents/capabilities/`：

| 类                     | 工具                           | 交互模式     |
| ---------------------- | ------------------------------ | ------------ |
| `DelegationCapability` | `aurora.agent.delegate`        | 就地决策     |
| `WaitCapability`       | `aurora.agent.wait`            | 就地决策     |
| `ClaimCapability`      | `aurora.situation.claim`       | 就地决策     |
| `MemoryCapability`     | `aurora.memory.query/remember` | 委派子 Agent |

### 交互模式

- **就地决策**：直接返回 `AgentDecision`（如 delegate → delegations，wait → wait_for_children）
- **委派子 Agent**：返回 `AgentDecision(delegations=(...))`
- **直调服务**：能力持有 service 引用，返回 `AgentDecision(model_request=...)`
- **多轮协商**：通过 continuation 先反问模型再决定

### 工具定义装配

ToolAgent 聚合工具定义：外部工具来自 `context.capabilities`，内部工具来自各 Capability 的 `tool_definitions(context)`。

## Agent 能力授权

`config/agents.toml` 中每个 profile 声明：

- `capabilities`：精确 Tool ID、package 末尾通配（`com.tencent.qq.*`）或 `*`（全部）
- `can_delegate`：是否可创建子 Agent
- `allowed_children`：可创建的子 profile 列表
- `model_role`：模型角色（如 `fast`、`agent`）

内建 root 与 worker profile 默认使用 `*`。能力策略是部署者可选的收窄，不是 Platform 强制分类。

## Agent 工具自由

Agent 从 AMP source、session、data、Brain Context 和工具描述自行判断：

- 是否需要回应
- 使用来源平台还是另一平台
- 调用一个还是多个工具
- 是否委派子 Agent
- 何时结束工作

Kernel 和 Platform 不推断 reply、relay、proactive 等意图。来源 Platform 不参与工具过滤。

## 约束

- Agent handler 不得持有 Provider client 或 Platform client
- 每 turn 恰好一个主要动作
- Provider parallel tool calls 关闭
- 子 Agent 只能通过 completion artifacts 回报父级
