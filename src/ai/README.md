# 模型网关

`src.ai` 统一 AuroraBot 的模型角色、Provider 路由、原生工具调用、Responses continuation、用量、费用、超时与取消。
Agent handler 不直接访问 Provider client，而是通过 Kernel 创建模型 Activity；异步 dispatcher 调用
`ModelGatewayService`，再以 `model.completed` 或 `model.failed` 邮箱消息恢复请求方 Agent。

## 公共契约

- `src.ai.contracts.ModelRequest`：角色、消息、所需能力、tools、tool choice、continuation、取消策略和受控参数。
- `src.ai.contracts.ModelResult`：规范化文本、最多一个 tool call、finish reason、用量、费用和 JSON continuation。
- `src.ai.vnext.ModelGatewayService`：能力协商、参数校验、双通道调用和统一结果规范化。
- `src.ai.gateway`：LiteLLM 执行、任务中断、费用追踪和 Provider 适配；是 service 的内部执行设施。

Provider 原生 Python 对象不得落盘。Responses output item、encrypted reasoning 和 Chat assistant tool call 只能以
公共契约定义的可序列化 JSON 保存。

## 模型通道

| endpoint | 用途 | continuation |
| --- | --- | --- |
| `chat_completions` | fast/quality 等聊天与原生 tools | 重放 assistant tool call、可用推理字段和 tool result |
| `responses` | 需要原生 Responses 的 agent | `store=false`，重放 output item 与 `function_call_output` |

两条通道都设置 `parallel_tool_calls=false`。一步只接受零或一个工具调用，多调用响应会被拒绝，不在 Kernel 中
隐式并行或 join。

## 配置与授权

角色和 Provider 只在 `config/aurora.toml` 的 `[models.roles.*]`、`[models.providers.*]` 中声明。角色包括模型、
Provider、endpoint 和能力；密钥字段只保存环境变量名。具体模型由 TOML 决定，代码和文档不建立第二套默认值。

调用参数不能覆盖 `model`、密钥、Provider 地址、tools、存储或并行策略。Agent profile 还必须在 `agents.toml` 声明使用的
模型角色；Kernel 会在创建请求前校验授权。工具参数在生成 `effect.requested` 前再次按不可变能力目录的 JSON Schema
校验。

## 调用生命周期

```text
Agent → model Activity → dispatcher → ModelGatewayService
                                      ├─ Chat Completions tools
                                      └─ Responses agent
   ← model.completed / model.failed ← normalized result
```

模型网络等待不占用 Agent turn。重启时残留请求会转为 `interrupted_by_restart`，默认不静默重试。全局模型并发、
交互优先级和自主请求取消由 `AuroraRuntime` 管理。

## 费用与日志

每次调用统一记录 token、费用、角色、模型、endpoint、延迟和结果状态。费用优先使用 LiteLLM 定价；缺失时可由
`src.ai.models` 查询定价数据，仍不可用则记录 warning 和零估值，不阻塞因果结果。

日志遵守根目录 `LOGGING.md`：INFO 只记录稳定标识和摘要，不记录完整 prompt、响应、continuation、密钥或用户载荷。
完整调用事实以脱敏的 Kernel 审计记录为准。
