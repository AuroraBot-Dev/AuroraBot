# RFC 0022：可组合 Agent 能力注册与工具分发

状态：已接受
日期：2026-07-23

## 背景

RFC 0012 定义了同构 Agent 运行时：所有 Agent 使用同一生命周期与消息协议，ToolAgent 作为认知 handler 负责模型调用
和工具分发。当前 ToolAgent 对内部工具（delegate、wait、claim、memory）采用硬编码 `if/elif` 链：

```text
ToolAgent._handle_model_result()
  ├─ call.name == "aurora.agent.delegate"      → 就地处理
  ├─ call.name == "aurora.agent.wait"          → 就地处理
  ├─ call.name == "aurora.situation.claim"     → 就地处理
  ├─ call.name == "aurora.memory.query"        → 委派 MemoryAgent
  ├─ call.name == "aurora.memory.remember"     → 委派 MemoryAgent
  └─ 其他                                      → 匹配外部 CapabilityDescriptor
```

内部工具的名字、参数 schema、条件逻辑和决策生成全部耦合在 ToolAgent（`src/agents/tool_agent.py`）和
`src/agents/tools.py` 两个文件中。新增一个 bot 自身能力（Live2D 控制、语音 TTS、算术引擎等）需要：

1. `tools.py` 添加常量和处理函数
2. `tool_agent.py` 添加 elif 分支和 handler 方法
3. `contracts/agent.py` 添加 AgentContext / AgentLimits 字段
4. `contracts/configuration.py` 添加 AgentRuntimeConfig 字段
5. `localhost/runtime.py` 添加 `_load_handler` 中的 `install_*` duck-typing
6. `kernel/runtime.py` 传递新字段到 AgentContext
7. `config/` 添加配置文件节

这与 RFC 0018 为外部平台工具建立的注册式扩展形成矛盾：平台外设新增工具不改 ToolAgent 一行代码，bot 自身能力
反而要求修改核心框架。

## 目标

1. **能力定义自包含**——每个内部能力在一个文件中声明工具 schema、条件开关与处理逻辑。
2. **ToolAgent 保持薄层**——不区分内部/外部工具，统一走注册 + 多态 dispatch。
3. **新增能力触碰最小化**——写一个 Capability 类 + 一行注册，不改框架核心。
4. **不必向后兼容**——直接切换到新基线。

## 决策

### 1. Capability 协议

在 `src/contracts/agent.py` 新增 `Capability` Protocol，定义三项契约：

```python
class Capability(Protocol):
    """Bot 自身的一项能力：声明工具、按上下文决定是否展示、处理模型工具调用。"""

    @property
    def tool_names(self) -> frozenset[str]: ...

    def tool_definitions(self, context: AgentContext) -> tuple[ToolDefinition, ...]: ...

    def handle_tool(self, call: ToolCall, context: AgentContext) -> AgentDecision | None: ...
```

- `tool_names` 返回该能力拥有的全部工具名（用作快速索引和注册表构建）
- `tool_definitions(context)` 给定 AgentContext，返回当前回合应展示的工具定义（上下文感知开关）
- `handle_tool(call, context)` 处理一个模型工具调用，返回 `AgentDecision` 或 `None`（表示不处理，由下一个能力或
  外部工具接管）

`ToolCall` 以 dataclass 形式定义于 `src/contracts/model.py`，包含 `name`、`arguments`、`call_id` 三个字段。这是
当前 `ModelResult.tool_calls` 列表项的离散化表示。

能力可以选择以下交互模式之一，或自由组合：

- **就地决策**：直接返回 `AgentDecision`，如 delegate→delegations, wait→wait_for_children
- **委派子 Agent**：返回 `AgentDecision(delegations=(DelegationRequest(...),))`，由独立 handler 执行
- **直调服务**：能力内部持有 service 引用，直接调用并将结果注入 `ModelContinuation`，返回
  `AgentDecision(model_request=...)`
- **多轮协商**：先反问模型再决定策略，通过 continuation 实现

框架不规定能力的交互模式，只要求返回合法的 `AgentDecision`。

### 2. 内建 Capability 拆分

现有 ToolAgent 中五类内部工具迁移为独立 Capability 类，位于 `src/agents/capabilities/` 下（子包化）：

| 类                     | 工具                                            | 交互模式                                   | 新文件                   |
| ---------------------- | ----------------------------------------------- | ------------------------------------------ | ------------------------ |
| `DelegationCapability` | `aurora.agent.delegate`                         | 就地决策                                   | `capability_delegate.py` |
| `WaitCapability`       | `aurora.agent.wait`                             | 就地决策                                   | `capability_wait.py`     |
| `ClaimCapability`      | `aurora.situation.claim`                        | 就地决策 + claims                          | `capability_claim.py`    |
| `MemoryCapability`     | `aurora.memory.query`, `aurora.memory.remember` | 委派子 Agent（有配置时）/ 降级（无配置时） | `capability_memory.py`   |

每个 Capability 的构造函数接受所需依赖（如 MemoryService 引用、agent profile 名称），由组合根注入。
`tool_names` 返回常量幂等集，`tool_definitions` 实现上下文条件判断，`handle_tool` 实现纯分发。

### 3. ToolAgent 重构

ToolAgent 从当前 239 行缩减为约 80 行，核心流程变为：

```text
handle(context)
  ├─ model.completed  → _handle_model_result
  │    ├─ 遍历 self._capabilities，命中则返其 decision
  │    └─ 未命中 → 外部 CapabilityDescriptor fallback
  ├─ tool.*           → _resume_tool（续跑，无变化）
  └─ 其他             → _request_model（组装 capabilities 的全部工具定义 + 外部工具）
```

ToolAgent 通过 `install_capabilities(capabilities)` 接收能力列表，存储在 `self._capabilities` 中。同时维护
一个 `tool_name → Capability` 的 dispatch 字典以优化查找。

### 4. 工具定义装配

`build_tool_definitions()` 从 `tools.py` 中移除内部工具定义部分，改为在 ToolAgent 中聚合：

```python
def _collect_tool_definitions(self, context: AgentContext) -> tuple[ToolDefinition, ...]:
    tools: list[ToolDefinition] = []
    # 外部工具（来自平台 capability catalog）
    for descriptor in context.capabilities:
        tools.append(capability_tool_definition(descriptor))
    # 内部能力工具
    for cap in self._capabilities:
        tools.extend(cap.tool_definitions(context))
    ...
    return tuple(tools)
```

`capability_tool_definition()` 和 `complete_task` 注入逻辑保留在 `tools.py` 中，仅服务外部工具。

### 5. Handler 加载扩展

`_load_handler()` 在 `src/localhost/runtime.py` 中新增 `capabilities` 参数，通过 duck-typing 注入：

```python
def _load_handler(
    specification: str,
    composer: PromptComposer,
    memory_service: Any = None,
    capabilities: tuple[Capability, ...] = (),
) -> AgentHandler:
    ...
    cap_installer = getattr(handler, "install_capabilities", None)
    if callable(cap_installer):
        cap_installer(capabilities)
    ...
```

只有实现了 `install_capabilities` 的 handler（即 ToolAgent）会接收能力列表。现有 handler（MemoryAgent）无感知。

### 6. 组合根装配

`AuroraRuntime.create()` 中新增 `_build_capabilities()` 工厂函数，创建内建能力元组并传递给 `_load_handler`。
能力列表是可扩展的——未来新增能力只需在此工厂中添加一行。

### 7. 与现有 RFC 的关系

- **扩展 RFC 0012**：Agent handler 契约不变（`AgentHandler.handle`）；新增的 `Capability` Protocol 是 handler 内部的
  组合机制，不改变 AgentDecision 语义或 mailbox/message 协议。
- **补充 RFC 0018**：外部工具走平台 `CapabilityDescriptor` + `ToolExecutor` 路径，内部能力走
  `Capability` + `AgentDecision` 路径。两者在 ToolAgent 中统一为同一次模型调用的扁平工具面，模型不感知内/外边界。
- **不改变 RFC 0019**：提示词装配不受影响。
- **不改变 RFC 0021**：内存读写逻辑从 ToolAgent 迁移至 MemoryCapability，MemoryAgent 不变，MemoryService 不变。

### 8. 向后兼容

- `memory_agent_profile` 在 `AgentContext`、`AgentLimits`、`AgentRuntimeConfig` 和 `config/aurora.toml` 中继续保留。
  MemoryCapability 从其构造函数接收 profile 名称（默认 `"builtin.memory"`），不读取 AgentContext 上的该字段。
  该字段可在后续 RFC 中废弃。
- `src/agents/tools.py` 中的内部工具常量（`DELEGATE_TOOL` 等）迁移至各自 Capability 类；外部引用它们的地方
  （如测试、其他模块）改为从 Capability 类导入或保留向后兼容别名至下一主版本。

## 非目标

- 不在本 RFC 中新增 Live2D、语音或其他具体能力。
- 不修改 Kernel 的消息 dispatch、决策应用或 causal 记录逻辑。
- 不改变平台工具（外部 CapabilityDescriptor）的注册和执行路径。
- 不将能力支持运行时热加载（启动时静态装配即可）。

## 验收标准

1. ToolAgent 不包含对 `DELEGATE_TOOL`、`WAIT_TOOL`、`CLAIM_TOOL`、`MEMORY_QUERY_TOOL`、`MEMORY_REMEMBER_TOOL`
   的任何硬编码分支。
2. 新增一项模拟能力（如 `EchoCapability`，注册 `aurora.test.echo` 工具，收到调用后返回 `Completion(text=echo...)`）
   仅需写一个新类并在工厂中注册一行，不改 ToolAgent、Kernel 或 contracts。
3. 现有 delegate / wait / claim / memory 行为与重构前完全一致，通过所有现有测试。
4. 外部平台工具（Console send、Dashboard send、MCP tools）继续正常工作。
5. `memory_agent_profile` 配置继续生效；不配置时 MemoryCapability 降级为返回 `memory.unavailable`。
6. `AgentDecision`、`AgentContext`、`AgentHandler` 接口不被破坏。
