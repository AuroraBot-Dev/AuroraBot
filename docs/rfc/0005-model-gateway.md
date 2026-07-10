# RFC 0005：模型网关

状态：已接受
日期：2026-07-11

## 目标

`src/ai` 是所有模型调用的统一入口，不限于文本 LLM。它管理模型角色、Provider 路由、能力协商、调用中断、节流、参数传递、使用量和计费。旧 LiteLLM 网关是其执行引擎，不是 Node 的公开依赖。

## 已确认决策

- 节点请求角色而不是硬编码模型，例如 `fast`、`quality`、`multimodal`、`embedding`，未来可加入 `tts` 等角色。
- 节点提交声明式 `ModelRequest`：输入、所需能力、预算、取消策略、重试策略和响应模式；不得直接持有 Provider client。
- 网关必须在调用前协商能力。典型能力包括 tools、结构化输出、流式、视觉、embedding 和 provider-native Responses API。
- 支持两种响应模式：`normalized` 用于可移植节点；`native` 用于确实需要厂商原生端点或对象的节点。持久化记录必须是可序列化的规范 JSON，不得把 Python 原生响应对象写入工作区。首版 LiteLLM 适配器支持 `normalized`，对 `native` 必须在调用前拒绝并说明原因。
- Tool 定义与 tool call 结果必须拥有统一中间表示；Provider 专有字段只能经显式 native 通道使用。

### 请求、结果与重试

`ModelRequest` 必须包含角色、消息、所需能力、响应模式、预算和取消策略；可选携带输出 JSON Schema。预算至少包括最大输出 token、超时和可选最大成本。默认重试策略为 `none`；调用方必须显式声明有限重试，首版不自动重试。

`ModelResult` 必须包含路由后的模型标识、协商结果、规范化文本或 JSON、用量、成本和诊断。Provider 原生对象只能留在进程内；任何审计记录仅保存其规范 JSON 表示。

### Provider 路由

Provider 仅由 `aurora.toml` 声明。首版支持 LiteLLM 标准路由和 `openai_compatible` HTTP 适配器；例如 SiliconFlow 由 `base_url`、密钥环境变量和 Provider ID 描述。Provider 不通过 OpenAI 原生响应通道或隐式 Python 注册定义。第三方 Python Provider 插件等待 RFC 0004。

### 结构化结果与效果

网关优先协商 Provider 结构化输出；角色不支持时，且请求允许 `json_text_fallback`，使用 JSON 文本提取和请求 schema 校验。无法得到合法 JSON 时，模型决定必须变为 schema 合法的 `no_action`，不得猜测效果。

模型调用是 Kernel 授权的内部异步能力，不是 Platform 效果。Kernel 为请求、完成或失败分别创建带因果父级的审计记录。模型节点生成的 `effect.requested` 仍由 Platform 唯一执行。

Platform 能力必须声明参数 JSON Schema。Kernel 在发布 `effect.requested` 前校验节点授权、能力存在和参数 schema；未通过校验的模型决定不得产生效果。

## 验收方向

1. 同一节点在声明 `normalized + tools` 时能够跨兼容 Provider 工作；声明 `native` 时，网关要么提供该模式，要么在调用前给出明确、可诊断的拒绝。
2. 结构化输出不可用时，允许的 JSON 文本回退只能生成经 schema 校验的结果或 `no_action`。
3. 缺少密钥、能力不支持、取消、超时、预算超限和 Provider 失败均可追溯，且默认不重试。
4. SiliconFlow 类 OpenAI-compatible Provider 可完全由 TOML 配置路由。
