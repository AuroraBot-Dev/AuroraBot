# RFC 0005：模型网关

状态：已接受
日期：2026-07-11
修订：2026-07-15

## 目标

`src/ai` 是所有模型调用的统一入口，不限于文本 LLM。它管理模型角色、Provider 路由、能力协商、原生工具调用、
调用中断、节流、受控参数、使用量和计费。LiteLLM 是内部执行设施，不是 Node 的公开依赖。

RFC 0008 扩展本文的请求/结果契约，并定义 Chat Completions tools 与 Responses 双通道、异步 dispatcher 和
Episode continuation；冲突处以 RFC 0008 为准。

## 决策

### 角色与授权

- Node 请求角色而不是硬编码模型，例如 `fast`、`quality`、`agent`、`multimodal`、`embedding`；后续可增加
  `tts` 等角色。
- Node 通过 Kernel 提交声明式 `ModelRequest`，不得持有 Provider client 或绕过 Kernel 发起认知调用。
- 网关在调用前协商 tools、结构化输出、视觉、embedding、Responses 等能力；不满足时在产生费用前拒绝。
- Node 可用角色由 `nodes.toml` 显式授权，模型与 Provider 由 `aurora.toml` 结构化声明。

### 请求与结果

`ModelRequest` 包含角色、消息、所需能力、预算、tools、tool choice、串行策略、continuation、取消策略和受控
Provider 参数。调用方不得通过参数覆盖模型、密钥、Provider 地址、tools、存储或并行策略。

`ModelResult` 包含路由模型、协商能力、规范化文本、零或一个 Tool Call、finish reason、用量、费用、诊断和可
序列化 continuation。Provider 原生 Python 对象只存在于调用进程内，不得写入工作区。

默认重试策略为 `none`。任何重试必须由明确且有界的策略授权；重启后残留请求转为
`interrupted_by_restart`，不静默重放。

### Provider 与 endpoint

Provider 只由 `aurora.toml` 声明，当前支持 LiteLLM 标准路由和 `openai_compatible` HTTP 适配器。模型角色显式
选择 `chat_completions` 或 `responses` endpoint；Responses 角色必须声明 `native_responses` 能力。

- Chat 通道透传原生 `tools/tool_choice`，规范化 Tool Call，并在续跑时重放 assistant tool call、可用推理字段
  和 tool result。
- Responses 通道使用原生 Responses endpoint，设置 `store=false` 与 `parallel_tool_calls=false`，按需请求
  encrypted reasoning，并重放 output item 与 `function_call_output`，不依赖 Provider 托管会话。

第三方 Python Provider 自动发现、签名和来源验证不属于当前契约。

### 结构化结果与效果

网关可以协商 Provider 结构化输出；角色不支持时，只有请求显式允许 `json_text_fallback` 才可执行 JSON 文本提取
和 schema 校验。无法得到合法 JSON 时，规范化决策必须成为 `no_action`，不得猜测效果。

模型调用是 Kernel 授权的内部异步能力，不是 Platform 效果。Kernel 分别记录请求、完成或失败。模型输出文本不
产生外部效果；Node 只有通过声明过的能力生成 `effect.requested`，才能请求 Platform 执行。

Platform 能力声明参数 JSON Schema。Kernel 在发布效果请求前校验 Node 授权、能力存在和参数 schema；非法或
未授权 Tool Call 只形成审计错误。

## 验收标准

1. Chat tools 与 Responses tools 使用正确的原生请求形状，并返回统一、可序列化的结果。
2. 结构化输出不可用时，允许的 JSON 文本回退只生成经 schema 校验的结果或 `no_action`。
3. 缺少密钥、能力不支持、取消、超时、预算超限和 Provider 失败均可追溯，且默认不重试。
4. OpenAI-compatible Provider 可完全由 TOML 配置路由，密钥仅由声明的环境变量提供。
5. 两条 endpoint 统一进入用量、费用、超时、取消和诊断记录。
