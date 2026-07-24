# 0101：数据契约

状态：已接受
日期：2026-07-23
来源：取代 RFC 0003、0004；整合自 RFC 0012、0014、0018、0022

## 职责

`src/contracts/` 定义所有无上层依赖的稳定数据契约。不依赖其他项目包，不持有业务逻辑。

## AMP 信封

Platform 与原生 App 以 UTF-8 JSON 交换 AMP。最小结构：

```json
{
  "header": {
    "protocol": "amp/1.0",
    "method": "aurora/event",
    "message_id": "uuid",
    "timestamp": "2026-07-23T00:00:00+00:00",
    "source": { "app": "platform.example", "instance": "default" }
  },
  "payload": {
    "type": "message.received",
    "session_id": "session-id",
    "summary": "human-readable summary",
    "data": {},
    "expire_at": null
  }
}
```

`header.method` 描述传输动作；`payload.type` 描述领域事实。AMP 是不可变跨边界事实。
入口以 `header.message_id` 去重；重放不得产生重复效果。

### 领域事件类型

- `message.received`：外部通信输入
- `system.tick`：自主心跳
- `tool.succeeded` / `tool.failed` / `tool.unknown`：Tool outcome（仅由 localhost 内部窄端口提交）

外部 AMP 或 MCP notification 不得伪造 `tool.*` 保留类型。

## AgentContext

Kernel 在每个 Agent turn 提供只读上下文：

| 字段            | 来源           | 说明                                    |
| --------------- | -------------- | --------------------------------------- |
| `task_id`       | Kernel         | 所属 Task                               |
| `agent_id`      | Kernel         | 当前 Agent 标识                         |
| `profile_id`    | 配置           | Agent profile 名称                      |
| `brain_context` | BrainContext   | 全局活跃 Task/Agent/Situation 投影      |
| `input_message` | Kernel mailbox | 当前消费的消息与 payload                |
| `capabilities`  | 平台 catalog   | 当前回合可用的全部 CapabilityDescriptor |
| `limits`        | 配置           | 模型调用数、工具调用数、持续时间等      |
| `children`      | Kernel         | 当前活跃子 Agent 状态摘要               |

## AgentDecision

Agent handler 必须返回以下动作之一（每 turn 恰好一个主要动作）：

| 动作            | 说明                                   |
| --------------- | -------------------------------------- |
| `model_request` | 请求模型调用，含角色、消息、工具定义等 |
| `tool_request`  | 请求执行一个 Tool，含 capability、参数 |
| `delegations`   | 创建一个或多个子 Agent                 |
| `completion`    | 完成当前 Agent 工作                    |
| `failure`       | 标记 Agent 失败                        |

ToolRequest 结构：

```text
capability      # Tool ID
parameters      # JSON-serializable dict
complete_task   # bool：成功后是否结束 Task/子 Agent
tool_call_id    # 可选，关联模型 Tool Call
continuation    # 可选，Provider continuation
```

`complete_task` 是 Runtime 控制字段：仅当原始 Tool schema 未定义同名属性时才注入给模型；
若原始 schema 已占用，schema 与参数原样传递，本次 Runtime 控制值为 `false`。

## Model 契约

`ModelRequest` 包含：角色、消息、所需能力、预算、tools、tool choice、continuation、取消策略。

`ModelResult` 包含：路由模型、协商能力、规范文本、ToolCalls、finish reason、用量、费用、诊断、可序列化 continuation。

`ToolCall` 以 dataclass 定义：`name`、`arguments`、`call_id`。

Provider 原生 Python 对象只存在于调用进程内，不得写入工作区。

## Capability 协议

```python
class Capability(Protocol):
    @property
    def tool_names(self) -> frozenset[str]: ...
    def tool_definitions(self, context: AgentContext) -> tuple[ToolDefinition, ...]: ...
    def handle_tool(self, call: ToolCall, context: AgentContext) -> AgentDecision | None: ...
```

内建能力（delegate、wait、claim、memory）各自实现此协议。外部平台工具走 `CapabilityDescriptor` + `ToolExecutor`。

## ToolDescriptor

统一工具描述符，不包含分类标签：

```text
id                   # 全局唯一 Tool ID，如 org.aurora.console.send
description          # 自然语言描述
parameters_schema    # JSON Schema
```

内建 Platform 使用稳定前缀 `org.aurora.<platform>.<tool>`。MCP App 的 `raw_name` 映射为
`<configured-package>.<raw_name>`。

## 配置 DTO

`load_configuration(project_root)` 返回不可变 `AuroraConfig`。DTO 与纯校验工具（`_require_keys`、`_string`、`_table` 等）位于 `src/contracts/configuration.py`，不含任何 I/O 或 TOML 解析。

`src/config` 提供配置加载与进程级单例：
- `load_configuration(root, profile)` — 读取所有 TOML、profile 合并、组装 AuroraConfig
- `init(root, profile)` — 进程早期显式加载，生成不可变快照并注册
- `get()` — 所有包零参数获取当前配置
- `reload()` — 热重载全部 TOML 并通知订阅者
- `subscribe(callback)` / `unsubscribe(callback)` — 注册重载回调

`PLATFORM_NAMES` 由 `PlatformPreference` 字段名派生，位于 contracts 层；用于 CLI 参数生成、平台选择校验和配置段键名验证。

## 约束

- 所有 contract dataclass 优先 `slots=True`
- 公开 API 提供完整类型注解
- AMP 正文、SOUL 内容、密钥不得进入 INFO 日志
- 配置快照必须可追踪来源（文件、profile、SOUL 版本）
