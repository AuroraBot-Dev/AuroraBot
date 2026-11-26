# 配置与 MCP

核对日期：2026-11-10。首次启动见[助手指南](../examples/START.md)，运行入口见[操作指南](operations.md)。

## 配置与数据目录

安装助手默认使用 `build/onboarding`，正式产品默认使用 `data`。两者独立；助手可以按用户要求修改正式配置，不会自动复制自己的历史或覆盖已有配置。

| 相对于数据目录的位置 | 内容 |
| --- | --- |
| `config/host.toml` | 显式插件列表与装配 ID |
| `config/org.aurora.bot/config.toml` | Bot 实例、模型角色、工具与功能开关 |
| `config/org.aurora.adapter/model/profiles.toml` | 供应商、模型、适配器与凭证环境变量名 |
| `config/org.aurora.adapter/model/bindings.toml` | reasoning / cadence 等角色到 profile 的绑定 |
| `config/org.aurora.adapter/mcp.toml` | MCP 连接和工具选择 |
| `config/org.aurora.world/config.toml` | 已启用 world 配置插件时的来源与视图 |
| `config/org.aurora.bot/cadence.toml` | 已启用 cadence 时的决策节律配置 |
| `config/org.aurora.bot/memory.toml` | 已启用记忆插件时的向量角色与分块配置 |
| `framework/ctx.json` | 持久业务快照 |
| `namespaces/` | 按命名空间隔离的文件及 SQLite 归档 |
| `logs/` | 宿主日志 |

配置服务只复制缺失文件，全部结构与关联校验通过后再注入非持久 ctx 状态。修改 TOML 后正常重启宿主；运行期 ctx 覆盖不自动写回文件或重建资源。模型、MCP 凭证在运行期从环境解析，不写入模板和快照。

## 模型

每个 profile 配置 `adapter`、`model`，以及可选的 `provider`、`base_url`、`credential`、`capabilities`、`thinking`、`reasoning_effort`。支持情况以实际供应商为准，错误参数不会自动降级。

```toml
[primary]
adapter = "org.aurora.adapter:adapters/model/litellm/chat"
provider = "deepseek"
model = "deepseek-flash"
credential = "AURORA_MODEL_API_KEY"

[primary.capabilities]
streaming = true
tool_calls = true
file_input = false
```

这是助手的示例 profile；按你的供应商修改。`credential` 只填变量名，密钥由用户在环境或本机 `.env` 中设置。角色文件使用 `reasoning = "primary"`，Bot 使用 `model_role = "reasoning"`。首次助手只需要一个聊天模型，不需要 choice 模型。

需要思考时，在支持的 profile 中添加 `thinking` 表或 `reasoning_effort`；未填写时沿用供应商默认。文件输入须与模型真实能力一致，不能仅靠声明获得多模态能力。

聊天、choice 和 embedding 共用 `aurora-adapter[litellm]`，分别选择 `org.aurora.adapter:adapters/model/litellm/chat`、`.../choice`、`.../embedding`。三类角色都通过同一注册表解析并检查用途；choice 和 embedding 不接受 `capabilities`、`thinking`、`reasoning_effort`。模型路由、供应商参数与响应转换使用 LiteLLM；客户端保留实例连接所有权，不共享全局路由器或修改 SDK 全局设置。请求不自动重试、不跟随重定向。

### 从旧模型配置升级

已有 TOML 不会被模板覆盖，请在停止宿主后手动替换 profile 的 `adapter`：

| 旧值（均以 `org.aurora.adapter:adapters/model/` 开头） | 新值（相同前缀） |
| --- | --- |
| `litellm` | `litellm/chat` |
| `litellm_choice` | `litellm/choice` |
| `openai_embedding` | `litellm/embedding` |

旧 `openai_embedding` profile 还需增加 `provider = "openai"`，继续使用原有模型和 API 根地址。角色绑定名、凭证变量名和配置文件位置保持不变；安装依赖将 `aurora-adapter[embedding]` 改为 `aurora-adapter[litellm]`。没有旧 ID 别名或自动迁移。

本次没有改名业务状态 ID 或改变消息 JSON，既有业务快照无需改写。记忆索引指纹包含 adapter ID，因此升级后须显式调用 `memory_reindex` 才能搜索旧记忆；原文仍可读取或删除，升级过程不会调用供应商、重建索引或清理用户数据。自定义插件的 Python 接口与服务/schema ID 迁移见[模型边界](aurorabot-design-v0.2.3.md#模型边界)。

## 显式文本记忆（朴素 RAG）

长任务的工具结果限制与中途摘要由独立的 [context_management 配置](context.md#长任务上下文管理)提供；记忆插件不自动压缩当前模型输入。

`aurora_bot.memory` 是独立启用的 Bot 插件，首次安装助手不默认启用。插件默认使用普通 ReAct 工具，按需保存和检索文本；可额外开启 [压缩时自动保存](context.md#压缩时自动保存长期记忆)，将被压缩记录先落盘、摘要后台索引，不依赖模型主动调用保存工具。

先补齐以下配置，再在 `config/host.toml` 的现有 `plugins` 列表中添加 `"aurora_bot.memory"`。保留默认 Bot 的依赖插件，包括 `aurora_bot.assembly`、`aurora_adapter.model`、`aurora_config`、`aurora_agent.tools`；只安装包不等于启用插件。

在模型 `profiles.toml` 添加独立向量 profile，模型名称和地址按实际供应商修改。向量请求通过 LiteLLM `aembedding`，支持已接入实例传输的 OpenAI 兼容供应商，以及 Voyage、Cohere 等原生协议。下例使用 OpenAI 兼容的 `/embeddings` 端点，`base_url` 填包含 `/v1` 的 API 根路径，不填完整 `/embeddings` 路径；不接受聊天能力和思考配置。当前传输范围以 [LiteLLMClient](../packages/aurora_adapter/src/aurora_adapter/model/litellm.py) 为准，不等于 LiteLLM 的全部供应商；未接入的兼容服务可显式选择 `provider = "openai"`。

```toml
[memory_embedding]
adapter = "org.aurora.adapter:adapters/model/litellm/embedding"
provider = "openai"
model = "text-embedding-3-small"
base_url = "https://api.openai.com/v1"
credential = "AURORA_EMBEDDING_API_KEY"
```

在模型 `bindings.toml` 增加 `memory = "memory_embedding"`，保留原有 `reasoning` 等绑定。凭证从运行期环境读取；无鉴权的本地兼容服务可省略 `credential`。供应商依赖统一属于 `aurora-adapter[litellm]`，Bot 分发已包含此 extra；基础 adapter 和独立 agent 不因此依赖 HTTP 客户端或模型 SDK。

`config/org.aurora.bot/memory.toml` 在首次加载插件时从[包模板](../packages/aurora_bot/src/aurora_bot/memory/config.tomls/memory.toml)补缺，也可预先写入：

```toml
model_role = "memory"
chunk_chars = 800
overlap_chars = 120
index_version = "1"
```

在 Bot 的 `config/org.aurora.bot/config.toml` 中添加所需的工具选择，放在顶层 `[[tools]]` 数组内：

```toml
[[tools]]
tool = "org.aurora.bot:tools/memory/write"
instance_id = "memory/write"

[[tools]]
tool = "org.aurora.bot:tools/memory/search"
instance_id = "memory/search"

[[tools]]
tool = "org.aurora.bot:tools/memory/read"
instance_id = "memory/read"

[[tools]]
tool = "org.aurora.bot:tools/memory/delete"
instance_id = "memory/delete"

[[tools]]
tool = "org.aurora.bot:tools/memory/reindex"
instance_id = "memory/reindex"
```

工具配置不接受所有者覆盖，所有者取自装配绑定的 Bot `instance_id`。可只连接搜索和读取工具以提供只读记忆；重建工具也可在维护时单独连接。重启宿主后生效，发现定义不创建资源或发送 embedding 请求；启用 auto_compaction 后，启动会在后台处理已落盘的待索引摘要。

| 工具 | 用法 |
| --- | --- |
| `memory_write` | 提供 `memory_id`、`text`、`source`、`expected_revision`；新建时版本为空字符串，更新时使用上次读取返回的版本 |
| `memory_search` | 提供 `query`；`top_k` 默认 5、最多 10，`min_score` 默认 0.3，返回满足阈值的分块、来源、版本与字符偏移 |
| `memory_read` | 按 `memory_id` 读取完整原文与版本 |
| `memory_delete` | 提供 `memory_id` 与当前 `expected_revision`，同时删除原文及索引 |
| `memory_reindex` | 无参数，显式为当前实例的全部记忆重新计算向量；会调用所选 embedding 服务 |

每个实例最多保存 1000 条记忆，单条正文最多 16000 字符。版本是不透明字符串，调用方不能自行递增或推断。正文与来源均为显式记录，来源说明不表示事实已经核实。

原文与向量保存在 `namespaces/ns-org.aurora.bot/memory.sqlite3`，不写入 ctx 快照；备份需在停止宿主后同时保存此数据库与业务快照。更换模型、端点、分块参数或 `index_version` 后，搜索明确报告索引不匹配，须调用 `memory_reindex`；同名模型背后的向量空间发生变化时应手动增加 `index_version`。重建失败或取消不会提交部分索引，也不会删除原文。重建也受 Bot 的 `tool_timeout` 限制，大语料维护时需按供应商速度调整该超时。

## 本地 terminal MCP

助手使用的完整可复制模板是 [mcp.toml](../examples/onboarding/config.tomls/org.aurora.adapter/mcp.toml)。启动命令为 `uvx --from terminal-mcp==0.4.7 terminal-mcp`，工作目录是宿主明确传入的仓库根目录。首次下载需要网络。

| 远端工具 | Bot 中的名称 |
| --- | --- |
| session_create | terminal_create |
| session_send | terminal_send |
| session_interact | terminal_interact |
| session_read | terminal_read |
| session_list | terminal_list |
| session_close | terminal_close |
| session_wait_for | terminal_wait_for |

终端拥有当前用户的实际文件和进程权限，不是隔离沙箱。会话可以在同一助手后端内复用；后端退出会关闭自有 MCP 进程树，旧 session_id 不代表可恢复的进程。

local 配置中的 `command` 是参数数组，不拼接 shell；相对 `cwd` 基于宿主 workspace_root。子进程只继承 SDK 的基础环境，加上显式 `environment`，不会自动得到全部模型凭证。需要工具访问额外变量时显式配置，例如 `APP_TOKEN = "{env:APP_TOKEN}"`，不填凭证原文。

## 扩展 MCP 服务

Aurora 配置以 `schema_version = 2` 和 `[servers.<连接名>]` 组织，连接名是稳定身份。`type = "local"` 使用 command / cwd / environment；`type = "remote"` 使用 url / headers。两种传输均支持 legacy、auto 和固定协议选择，默认 legacy。启动、目录、执行与关闭分别有 timeout。

```toml
schema_version = 2

[servers.service]
type = "remote"
url = "http://127.0.0.1:8000/mcp"
required_capabilities = ["tools"]

[servers.service.tools]
include = ["echo"]
aliases = { echo = "service_echo" }
```

默认发现全部工具并自动命名；显式 include/exclude 控制集合，include=[] 不暴露工具，aliases 覆盖名称。安装助手只选择上表 7 个工具。公共动态定义属于 `org.aurora.adapter:tools/mcp/<工具名>`。

安装 extra 与启用插件分别处理。工具链需要 aurora_adapter.mcp、aurora_adapter.mcp.tools 及 agent 工具插件；默认 MCP Bot 装配另需 aurora_adapter.mcp.bot 与 aurora_bot.assembly。完整最小清单见助手的 [host.toml](../examples/onboarding/config.tomls/host.toml)。

独立生成正式 MCP 产品模板，可在目标目录不存在或已核对后执行：

```powershell
uv run --locked python -m aurora_adapter.mcp.preset data --api
```

它只补缺文件。已有 host 与候选不同会输出差异和 host.mcp.toml，不覆盖原选择，需审阅后显式应用。填写目标目录中的模型和 MCP 配置，再按操作指南启动。

旧 MCP 格式通过 `python -m aurora_adapter.mcp.migrate 旧文件 --output 新候选` 生成迁移候选；不会自动迁移快照、插件名或旧命名空间。其他客户端的 JSON 配置不能直接作为 Aurora TOML 使用。

## 世界与主动行为

正式产品可启用 aurora_world、aurora_world.configuration、aurora_world.environment，以及可选 aurora_adapter.mcp.world；world 配置用 sources 显式选择来源、source_id 和配置。MCP 来源还需 connection_id 和资源 URI，借用已配置客户端。安装助手不启用这些插件。

时间、天气、世界事件、cadence、笔记和计划唤醒的语义见[上下文与运行](context.md)。配置结构以包内模板和 schema 为准：[world](../packages/aurora_world/src/aurora_world/config.toml)、[MCP](../packages/aurora_adapter/src/aurora_adapter/config.tomls/mcp.toml)、[Bot](../packages/aurora_bot/src/aurora_bot/config.toml)、[cadence](../packages/aurora_bot/src/aurora_bot/cadence/config.tomls/cadence.toml)。
