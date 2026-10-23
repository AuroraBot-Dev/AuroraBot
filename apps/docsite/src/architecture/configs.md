---
order: 3
---

# 配置与存储

## 管理个人配置

内置配置位于工作目录的 `config/` 中。启动时自动补齐缺失文件，已有内容不覆盖。使用 `aurora config` 查看名称与路径，编辑与校验方法见[配置](../start/configs)。

修改配置后需要重启。`.env` 可补充尚未设置的环境变量，不覆盖已有进程环境；模型和应用配置填写密钥变量名，实际密钥放在 `.env` 或进程环境中。

## 按需求找到配置

| 需求                               | 相关配置                                               |
| ---------------------------------- | ------------------------------------------------------ |
| 设置 Bot 身份                      | `bot.toml`                                             |
| 调整默认 Agent、运行上限与日志级别 | `runtime.toml`、`engine.toml`                          |
| 调整人格、提示词和可用工具         | `agents.toml`、`prompts.toml`、`prompts/`、`tags.toml` |
| 更换模型与提供方                   | `providers.toml`、`endpoints.toml`                     |
| 调整思考时机                       | `cadence.toml`、`reactions.toml`、`rhythm.toml`        |
| 调整记忆范围与排序策略             | `memory.toml`、`memory_model.toml`、`scopes.toml`      |
| 接入外部应用                       | `apps.toml`、`platforms.toml`                          |
| 设置数据与日志位置                 | `storage.toml`、`artifacts.toml`                       |

各项字段以初始化后的配置说明为准。插件配置也可以通过 `aurora config` 查看实际路径。

## 更换模型

1. 在 `providers.toml` 中填写提供方、协议类型、密钥变量名及必要的服务地址。
2. 在 `endpoints.toml` 中选择提供方，填写远端实际模型名。
3. 在 `agents.toml` 中让需要调整的 Agent 引用对应端点。
4. 执行 `aurora config --check` 校验配置，再重启 Bot。

提供方的资源名是本地标识，`sdk_provider` 是协议类型，两者不能混用。OpenAI 兼容服务使用 `openai_compatible`、`sdk_provider = "openai"` 和服务提供的 `base_url`。

记忆与节律模型的训练及启用见[节律与记忆](./learning)，外部连接见 [MCP 应用接入](./mcp)。

## 持久数据与备份

`storage.toml` 设置世界数据与日志目录，`artifacts.toml` 设置内容存储目录。世界记录保存经历与结果，内容存储保存被引用的正文、权重等数据；运行日志用于诊断，不能代替这些持久数据。

备份时应同时保留世界数据与内容存储，只复制其中一部分可能导致历史记录无法完整读取。运行日志不记录 Prompt、消息正文、工具参数或密钥；业务数据仍可能包含对话和行动内容。

### 备份与恢复操作

文档待编写。
