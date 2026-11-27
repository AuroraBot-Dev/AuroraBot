# 配置与装配

核对基线：W08（2026-11-27）。首次使用见[安装助手](../examples/START.md)，启动与界面见[操作指南](operations.md)，插件作者见[元信息与装配约定](aurora-meta-proposal.md)。

## 三种文件各管什么

| 文件 | 职责 | 编辑位置 |
| --- | --- | --- |
| `plugin.meta.toml` | 插件的公开定义、插头、插槽、状态与资源角色 | 插件源码；随发行包发布 |
| `assembly.toml` | 启用哪些插件、创建哪些实例、如何绑定状态和资源、怎样接线 | 用户数据目录；可从完整预设复制 |
| `plugin.config.toml` 或能力专用 TOML | 模型参数、工具超时、视图长度等业务值 | 用户数据目录的 `config/<namespace>/` |

`config/host.toml` 只选择装配文件。相对路径以 `config/` 为起点：

```toml
assembly_file = "assembly.toml"
```

不要在 host.toml 添加 `plugins`、装配 ID 或功能开关。插件选择位于它指向的装配文件；安装包、启用插件、创建实例和建立连接是不同操作，互不自动推导。

## 数据与配置位置

安装助手默认使用 `build/onboarding`，正式产品默认使用 `data`。同一数据目录只能由一个宿主使用；初始化只补缺失文件，不复制另一宿主的历史，也不覆盖已有配置。

以下路径均相对于数据目录；配置文件是否出现取决于所选插件：

| 路径 | 内容 |
| --- | --- |
| `config/host.toml`、`config/assembly.toml` | 宿主选择与完整装配 |
| `config/org.aurora.model/profiles.toml` | 模型 profile、适配器、供应商参数、凭证变量名 |
| `config/org.aurora.model/bindings.toml` | 通用模型角色绑定；当前文件预设直接选择 profile |
| `config/org.aurora.agent/react.toml` | `max_iterations`；省略表示不限轮次 |
| `config/org.aurora.agent/model_call.toml` | `streaming` |
| `config/org.aurora.agent/react_defaults.toml` | `system_prompt` |
| `config/org.aurora.agent/input_budget.toml` | `max_chars` |
| `config/org.aurora.agent/compaction.toml` | 摘要长度、超时与工具观察限额 |
| `config/org.aurora.tools/executor.toml` | 工具执行 `timeout` |
| `config/org.aurora.mcp/plugin.config.toml` | MCP 服务与目录选择 |
| `config/org.aurora.world/plugin.config.toml` | 世界来源参数及近期视图 |
| `config/org.aurora.bot/actions.toml` | 动作证据读取长度 |
| `config/org.aurora.bot/world_view.toml` | 业务视图内容、长度和归档读取长度 |
| `config/org.aurora.bot/cadence.toml` | 节律决策参数 |
| `config/org.aurora.memory/plugin.config.toml` | 记忆分块与索引版本 |
| `framework/ctx.json` | 持久业务快照；不包含配置状态 |
| `namespaces/ns-<namespace>/` | 所属能力的文件与 SQLite 数据库 |
| `logs/` | 宿主日志 |

不存在统一的 Bot 大配置。预算、记忆、自身控制等能力是否创建，由装配实例和资源引用决定；修改业务 TOML 不会新增组件。配置状态不持久化，运行期覆盖不自动写回 TOML；修改配置或装配后正常重启。

## 选择完整预设

包内[预设目录](../packages/aurora_bot/src/aurora_bot/presets/)包含可直接读取的完整文件；这些文件不是相互叠加的片段。

| 预设 | 主要能力 | 需要的模型 profile |
| --- | --- | --- |
| `default.toml` | ReAct、运行入口、直接交流与空工具集合 | `primary`（chat） |
| `mcp.toml` | default 加 MCP 客户端、工具目录与动态工具集合 | `primary` |
| `world.toml` | default 加世界记录、来源与业务视图；不含 MCP/cadence | `primary` |
| `mcp-world.toml` | MCP 工具与世界来源共用客户端；不含 cadence | `primary` |
| `bot.toml` | MCP/world、环境来源定义、cadence 和 API；cadence 默认原样转交 | `primary` |
| `memory.toml` | default 加记忆工具、embedding、输入预算与压缩归档 | `primary`、`embedding` |
| `full.toml` | bot 加笔记、动作证据、自身控制、归档工具、记忆、压缩与 choice 资源 | `primary`、`embedding`、`decision`（choice） |
| [onboarding](../examples/onboarding/plugin.config.tomls/assembly.toml) | 独立安装助手、terminal MCP、48000 字符预算 | `primary` |

选用预设不代表已经配置外部服务；MCP 的默认服务集合、world 的默认来源集合均为空。full 声明了 choice 资源，但是否进行决策仍由 cadence 的 `[decision]` 参数决定。onboarding 不启用世界、节律或记忆。

MCP 初始化命令：

```powershell
uv run --locked python -m aurora_bot.mcp_preset data --api
```

需要 MCP 世界桥时加 `--world`。该命令生成 `host.toml`、完整装配及声明配置模板，不启动客户端。若已有装配不同，返回差异和 `config/assembly.mcp.toml` 候选，退出码为 2；原选择不变。审阅候选后明确修改 `host.toml` 的 `assembly_file`。

选择其他发行预设可使用现有 Python 初始化接口，例如在**新的独立目录**生成 full：

```powershell
uv run --locked python -c "from pathlib import Path; from aurora_bot.mcp_preset import initialize; raise SystemExit(initialize(Path('build/full'), preset='full'))"
```

当前命令行没有 `--preset` 选项。该接口只生成文件；填写所有必需 profile 后再启动。已有文件不会随新的预设自动升级。

## 模型与凭证

`profiles.toml` 中每个表是一份 profile。按自己的供应商填写 `provider`、`model` 和可选 `base_url`；示例适配器为 `org.aurora.model:adapters/litellm/chat`，需要启用 `aurora_model.litellm`。

`credential` 只填环境变量名。安装助手和 `aurora bot` 会加载指定的环境文件，通用 `aurora run/serve` 使用进程环境，不自动读取项目 `.env`。凭证不进入配置状态、业务快照或静态目录。

文件预设直接选择 profile。以下是现有装配的局部示例，**不是独立的完整文件**：

```toml
[instances.chat.options]
profile = "primary"

[instances.chat.states.profiles]
key = "org.aurora.model:state/config"
scope = "instance"
```

切换该实例使用的模型应修改 `instances.chat.options.profile`，并在 profiles.toml 提供对应表。不要通过修改 `bindings.toml` 的 reasoning/cadence/memory 字段推断当前预设会自动换模型；这些预设没有绑定角色状态。

chat、choice、embedding 分别使用 `adapters/litellm/chat`、`adapters/litellm/choice`、`adapters/litellm/embedding`。例如 memory 预设需要名为 `embedding` 的向量 profile；full 还需要名为 `decision` 的 choice profile。它们可以使用不同的凭证变量。

chat 的 `capabilities`、`thinking`、`reasoning_effort` 必须与供应商能力一致；choice/embedding 不接受这些聊天专用字段。模型种类由适配器检查，不把 chat 自动当作 choice。模型请求及工具调用的失败语义见[上下文与运行](context.md)。

## MCP 工具与来源

可复制的 terminal 模板见[助手 MCP 配置](../examples/onboarding/plugin.config.tomls/org.aurora.mcp/plugin.config.toml)。它使用固定的 `terminal-mcp==0.4.7`，只选择七个终端工具，映射为 terminal_create/send/interact/read/list/close/wait_for。首次启动由 uvx 下载依赖；初始化不启动终端。

MCP 文件使用服务名作为连接身份：

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

local 服务使用参数数组 `command`、可选 `cwd` 与 `environment`；相对 cwd 基于宿主 `--root`。子进程只继承基础环境及显式 environment，例如 `APP_TOKEN = "{env:APP_TOKEN}"`。remote 使用 url/headers。协议选择与 timeout 字段以[MCP 模板](../packages/aurora_mcp/src/aurora_mcp/plugin.config.toml)及声明契约为准。

MCP 服务的 tools.include/exclude 决定哪些远端定义进入目录；装配中的工具集合再决定使用哪些定义。动态 ID 为 `org.aurora.mcp:tools/<本地工具名>`。集合可以读取目录，也可显式选择工具；当前不要让显式 tools 与目录 include 重复选中同一个 ID，重复会使准备失败。需要单独指定某工具配置时，在目录规则中排除它，再显式列入。

例如在已有 MCP 预设中修改集合选择，以下仍为局部片段：

```toml
[instances.collection.options]
owner = "main"
instance_pattern = "{collection}/{name}"
location_field = "member"
tools = []
include = ["org.aurora.mcp:tools/*"]
```

MCP 工具桥和世界桥通过资源引用借用同一客户端。MCP 世界资源须在 world 的 `sources` 中明确填写 source、source_id、connection_id 和资源 URI；仅启用桥插件不会自动订阅来源。工具目录在 prepare 展开，运行中不热改集合、不自动重放工具请求。

terminal 拥有宿主用户的文件和进程权限。会话可在同一后端中复用；宿主退出会关闭自有 MCP 进程树，旧 session_id 不代表进程可以恢复。

## 显式文本记忆（朴素 RAG）

记忆由独立插件 `aurora_memory` 提供，压缩归档桥为 `aurora_memory.compaction`。使用 memory/full 完整预设比在现有文件中只追加插件名更直接：需要同时选择 embedding 实例、记忆资源、工具集合与生命周期连接。

业务配置位于 `config/org.aurora.memory/plugin.config.toml`：

```toml
embedding_id = "primary"
chunk_chars = 800
overlap_chars = 120
index_version = "1"
```

`embedding_id` 是索引身份标记，不是模型 profile 路由；实际 embedding 由装配资源引用决定。当前索引指纹使用上述记忆配置，**不会自动纳入所借用模型的 adapter/model/base_url**。因此更换模型、端点或向量空间时，须显式更新 embedding_id 或 index_version 并重建索引；不能依赖同维向量检测发现这种更换。

| 工具 | 作用 |
| --- | --- |
| `memory_write` | 保存原文、来源与版本；新建 expected_revision 为空字符串 |
| `memory_search` | 按 query 检索分块，返回来源、版本和字符偏移 |
| `memory_read` | 按 memory_id 读取全文 |
| `memory_delete` | 携带当前版本删除原文与索引 |
| `memory_reindex` | 为当前 owner 明确重建索引，会调用 embedding 服务 |

工具定义归 `org.aurora.memory:tools/<action>`。可在集合中只选择 read/search；owner 由装配明确分配，工具借用资源与输入输出地址，不反查 Bot WORK。

原文、向量与压缩归档保存在 `namespaces/ns-org.aurora.memory/memory.sqlite3`。备份需在宿主停止后同时保存数据库和业务快照。重建失败不会提交部分索引或删除原文；执行超时由工具执行器配置决定。记忆不自动注入每轮输入，模型按需检索。压缩归档的后台索引与恢复语义见[上下文与运行](context.md#压缩时自动保存长期记忆)。

## 安装边界与新基线

工作区使用 `uv sync --locked --all-packages`。分发安装时按所选能力安装 extra，再由装配文件显式启用插件：

| 安装 | 提供 |
| --- | --- |
| `aurora-model` / `[config]` / `[litellm]` | 模型协议 / 配置 / 供应商 SDK |
| `aurora-mcp` / `[tools]` / `[world]` | 客户端 / 工具桥 / 世界桥 |
| `aurora-agent[config]`、`aurora-tools[config]` | 执行能力各自的可选配置桥 |
| `aurora-bot[litellm,mcp]` | 使用 LiteLLM 的 MCP 产品组合所需依赖 |
| `aurora-bot[litellm,mcp-world,world,memory]` | full 组合所需依赖；CLI/API 另按宿主用途安装 |

基础 Bot 不带 world、MCP、memory 或供应商 SDK。安装 extra 不会隐式启用插件，也不会开放 API 端点。

本轮直接采用新环境、新数据目录和版本 2 装配。旧 adapter、Bot 聚合装配、大配置与旧模板路径均不提供别名；没有 `aurora_mcp.migrate` 命令。按新模板重新建立所需配置，凭证继续通过环境提供；不自动探测、转换、覆盖或删除旧目录。新基线内部支持正常停止后恢复，但不承诺旧基线快照透明续跑，未知状态不会被静默丢弃。
