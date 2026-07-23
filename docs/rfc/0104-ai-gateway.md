# 0104：AI 模型网关

状态：已接受
日期：2026-07-23
来源：取代 RFC 0005；整合自 RFC 0012、0018

## 职责

`src/ai/` 是所有模型调用的统一入口。管理模型角色、Provider 路由、能力协商、工具调用映射、
调用中断、节流、使用量和计费。LiteLLM 是内部执行设施，不是公开依赖。

## 模型角色

Agent 通过角色请求模型而非硬编码模型名：

| 角色         | 说明            |
| ------------ | --------------- |
| `fast`       | 快速分类/筛选   |
| `agent`      | 通用 Agent 推理 |
| `quality`    | 高质量长推理    |
| `multimodal` | 视觉/多模态     |
| `embedding`  | 向量嵌入        |

角色在 `aurora.toml` 的结构化 model 列表中声明，绑定具体 model name、Provider 和能力。

## 请求与结果

### ModelRequest

Agent 通过 Kernel 提交，包含：角色、消息、所需能力（tools、structured output 等）、budget、
tools、tool choice、continuation、取消策略。调用方不得通过参数覆盖模型、密钥、Provider 地址、
tools、存储或并行策略。

### ModelResult

网关返回：路由模型、协商能力、规范化文本、ToolCalls、finish reason、用量、费用、诊断、
可序列化 continuation。

默认重试策略为 `none`。重启后残留请求不静默重放。

## 双通道

模型角色显式选择 `chat_completions` 或 `responses` endpoint：

### Chat Completions 通道

- 透传原生 `tools/tool_choice`
- 规范化 Tool Call
- 续跑时重放 assistant tool call、推理字段和 tool result

### Responses 通道

- 使用原生 Responses endpoint
- `store=false`、`parallel_tool_calls=false`
- 按需请求 encrypted reasoning
- 续跑重放 output items 与 `function_call_output`
- 不依赖 Provider 托管会话（`previous_response_id`）

## 异步调度

模型调用是 Kernel 授权的内部异步能力，不是 Platform 效果：

- Agent 返回 `model_request` → Kernel 创建 model Activity
- 周期外 model dispatcher 执行实际 Provider 调用
- 完成/失败后以 `model.completed` / `model.failed` 邮箱消息恢复 Agent
- 交互请求优先于自主请求；全局模型并发为一

## 能力协商

网关在调用前协商 tools、结构化输出、视觉、embedding、Responses 等能力；
不满足时在产生费用前拒绝。

Tool 名称、描述和 schema 由 Tool 提供方管理，AI gateway 只做 Provider 协议需要的
Tool 名称别名映射，描述和 schema 原样透传。不包装或覆盖任何 Tool 描述。

`complete_task` 是 Agent Runtime 控制字段，由 ToolAgent 在安全时注入给模型的 Tool schema，
不属于 PromptComposer 或 AI gateway。

## 结构化输出

- 网关可协商 Provider 结构化输出
- 角色不支持时，仅当请求显式允许 `json_text_fallback` 才执行 JSON 文本提取和 schema 校验
- 无法得到合法 JSON 时返回 `no_action`，不得猜测效果

## Provider 配置

- Provider 只由 `aurora.toml` 声明
- 支持 LiteLLM 标准路由和 `openai_compatible` HTTP 适配器
- 密钥仅由声明的环境变量提供
- 第三方 Python Provider 自动发现不属于当前契约

## 约束

- Provider 原生 Python 对象不落盘
- 模型输出文本不产生外部效果——只有 Tool 调用才能产生
- 所有 endpoint 统一进入用量、费用、超时、取消和诊断记录
