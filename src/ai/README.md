# 模型如何参与 AuroraBot

模型为 AuroraBot 提供判断和语言能力，但它不是运行时本身，也不能凭一段文本直接改变外部世界。`src.ai` 的工作是把
不同 Provider 和调用方式收敛成一致的模型体验：Agent 只需要说明“需要哪种能力”，其余的选择、校验、用量记录和结果
规范化由模型网关完成。

## 一次模型调用会发生什么

1. Agent 返回一个模型请求，Kernel 将它保存为可追踪的 Activity。
2. dispatcher 根据模型角色选择 Provider、模型和 endpoint。
3. 模型网关校验能力与受控参数，然后发起 Chat Completions 或 Responses 调用。
4. 文本、至多一个工具请求、token、费用和 continuation 被规范化为可序列化结果。
5. `model.completed` 或 `model.failed` 回到 Agent 邮箱，Agent 从等待处继续。

网络等待不会占用 Agent turn。进程重启时，尚未完成的调用会明确失败为 `interrupted_by_restart`，而不是在无法确认
外部状态时静默重试。

## 选择模型

所有角色和 Provider 都在 `config/aurora.toml` 中声明：

```toml
[models.roles.fast]
provider = "deepseek"
model = "deepseek-v4-flash"
endpoint = "chat_completions"
capabilities = ["chat", "tools"]

[models.providers.deepseek]
adapter = "litellm"
secret_env = "DEEPSEEK_API_KEY"
```

角色描述“这次工作需要什么”，Provider 描述“到哪里完成它”。Agent profile 还需要在 `config/agents.toml` 中获得对应
角色和工具的授权。密钥字段只保存环境变量名，真实密钥不进入 TOML。

当前支持两种调用体验：

| 通道 | 适合什么 | 如何继续 |
| --- | --- | --- |
| `chat_completions` | 普通对话、快速判断和原生 tools | 重放 assistant tool call 与 tool result |
| `responses` | 需要原生 Responses 与 reasoning item 的 Agent | 使用 `store=false` 的可序列化 continuation |

两条通道每一步都只接受零或一个工具调用。真正的并行来自多个 Agent 的协作，而不是把一次模型响应中的多个 tool call
偷偷并行执行。

## 可靠性与隐私

- Provider 原生 Python 对象不会落盘，continuation 只保存公共契约允许的 JSON。
- 工具请求在变成环境效果前，还会按能力目录中的 JSON Schema 再次校验。
- 每次调用记录角色、模型、endpoint、延迟、token、费用和状态，但默认不记录完整 prompt 或回复正文。
- 缺少密钥、能力不匹配和不受控参数都会产生明确失败，不会悄悄降级到另一套行为。

公共数据结构见 `src.contracts.model`，调用编排见 `src.ai.vnext.ModelGatewayService`，底层 Provider 执行见
`src.ai.gateway`。日志与敏感信息边界见根目录 [LOGGING.md](../../LOGGING.md)。
