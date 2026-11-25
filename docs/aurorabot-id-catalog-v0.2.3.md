# AuroraBot 公共 ID 目录

核对日期：2026-11-10。文件名沿用现有引用；本页由当前工作区的 bootstrap、ctx 操作、生命周期、CLI 命令和全部已安装 aurora.plugins 定义实际登记后枚举。未启动装配、模型、MCP 或世界来源。旧设计中的规划 ID 见[归档](archive/2026-11-09/aurorabot-id-catalog-v0.2.3.md)。

## 身份与使用

ID 格式为 `<namespace>:<domain>/<local_path>`。表中只列实际定义；定义存在不表示插件已在用户宿主启用、组件已连接、端点已开放或运行资源已创建。命名空间不是权限边界。

状态值使用 ID 与精确 location 寻址。bot 的 instance_id、run_id、execution_id 分别表示实例、运行和一次执行；不要为每个运行另造定义 ID。control 与 agent 定义归所属包，bot 分配的运行地址仍归 bot。

MCP 动态工具以 `org.aurora.adapter:tools/mcp/<工具名>` 登记；连接目录返回之前无法枚举。组件实例和工具执行连接同样在装配阶段建立，不混入本静态表。运行期 ctx 服务由宿主绑定，查询列表不是远端访问白名单。

## 插件入口

安装与启用分开；requires 只校验显式启用的依赖。安装助手使用[最小插件清单](../examples/onboarding/config.tomls/host.toml)，正式产品可启用更多能力。

| entry point / Plugin.name | requires |
| --- | --- |
| `aurora_adapter.mcp` | `aurora_config` |
| `aurora_adapter.mcp.bot` | `aurora_adapter.mcp.tools`, `aurora_bot.assembly` |
| `aurora_adapter.mcp.tools` | `aurora_adapter.mcp`, `aurora_agent.tools` |
| `aurora_adapter.mcp.world` | `aurora_adapter.mcp`, `aurora_world.configuration` |
| `aurora_adapter.model` | `aurora_config` |
| `aurora_agent.model` | 无 |
| `aurora_agent.react` | 无 |
| `aurora_agent.react_defaults` | `aurora_agent.react`, `aurora_agent.model`, `aurora_agent.tools` |
| `aurora_agent.tools` | 无 |
| `aurora_api` | 无 |
| `aurora_bot.assembly` | `aurora_config`, `aurora_adapter.model`, `aurora_agent.model`, `aurora_agent.react`, `aurora_agent.tools`, `aurora_agent.react_defaults` |
| `aurora_bot.cadence` | `aurora_bot.assembly`, `aurora_world`, `aurora_config` |
| `aurora_bot.memory` | `aurora_bot.assembly`, `aurora_adapter.model`, `aurora_config`, `aurora_agent.tools` |
| `aurora_config` | 无 |
| `aurora_control` | 无 |
| `aurora_world` | 无 |
| `aurora_world.configuration` | `aurora_world`, `aurora_config` |
| `aurora_world.environment` | `aurora_world` |

## 静态定义

### org.aurora.adapter

| ID | kind | provider |
| --- | --- | --- |
| `org.aurora.adapter:adapters/model/litellm/chat` | `adapter` | `aurora_adapter.model` |
| `org.aurora.adapter:adapters/model/litellm/choice` | `adapter` | `aurora_adapter.model` |
| `org.aurora.adapter:adapters/model/litellm/embedding` | `adapter` | `aurora_adapter.model` |
| `org.aurora.adapter:assemblies/mcp/default_bot` | `assembly` | `aurora_adapter.mcp.bot` |
| `org.aurora.adapter:components/mcp/tool` | `component` | `aurora_adapter.mcp.tools` |
| `org.aurora.adapter:components/mcp/tool/execute` | `hook_handler` | `aurora_adapter.mcp.tools` |
| `org.aurora.adapter:configs/mcp` | `config` | `aurora_adapter.mcp` |
| `org.aurora.adapter:configs/model/bindings` | `config` | `aurora_adapter.model` |
| `org.aurora.adapter:configs/model/profiles` | `config` | `aurora_adapter.model` |
| `org.aurora.adapter:handlers/mcp/clean` | `hook_handler` | `aurora_adapter.mcp` |
| `org.aurora.adapter:handlers/mcp/configure` | `hook_handler` | `aurora_adapter.mcp` |
| `org.aurora.adapter:handlers/mcp/prepare` | `hook_handler` | `aurora_adapter.mcp` |
| `org.aurora.adapter:handlers/mcp/stop` | `hook_handler` | `aurora_adapter.mcp` |
| `org.aurora.adapter:handlers/mcp/tools/prepare` | `hook_handler` | `aurora_adapter.mcp.tools` |
| `org.aurora.adapter:registries/model/adapters` | `registry` | `aurora_adapter.model` |
| `org.aurora.adapter:schemas/model/chat/capabilities` | `schema` | `aurora_adapter.model` |
| `org.aurora.adapter:schemas/model/chat/chunk` | `schema` | `aurora_adapter.model` |
| `org.aurora.adapter:schemas/model/chat/request` | `schema` | `aurora_adapter.model` |
| `org.aurora.adapter:schemas/model/chat/response` | `schema` | `aurora_adapter.model` |
| `org.aurora.adapter:services/model/chat_client` | `service` | `aurora_adapter.model` |
| `org.aurora.adapter:services/model/choice_client` | `service` | `aurora_adapter.model` |
| `org.aurora.adapter:services/model/embedding_client` | `service` | `aurora_adapter.model` |
| `org.aurora.adapter:sources/mcp/resources` | `source` | `aurora_adapter.mcp.world` |
| `org.aurora.adapter:state/mcp/clients` | `state_key` | `aurora_adapter.mcp` |
| `org.aurora.adapter:state/mcp/config` | `state_key` | `aurora_adapter.mcp` |
| `org.aurora.adapter:state/mcp/world` | `state_key` | `aurora_adapter.mcp.world` |
| `org.aurora.adapter:state/model/bindings` | `state_key` | `aurora_adapter.model` |
| `org.aurora.adapter:state/model/config` | `state_key` | `aurora_adapter.model` |

### org.aurora.agent

| ID | kind | provider |
| --- | --- | --- |
| `org.aurora.agent:handlers/model_call` | `component` | `aurora_agent` |
| `org.aurora.agent:handlers/model_call/execute` | `hook_handler` | `aurora_agent` |
| `org.aurora.agent:handlers/react/build_prompt` | `component` | `aurora_agent` |
| `org.aurora.agent:handlers/react/build_prompt/execute` | `hook_handler` | `aurora_agent` |
| `org.aurora.agent:handlers/react/execute_tools` | `component` | `aurora_agent` |
| `org.aurora.agent:handlers/react/execute_tools/children` | `hook_slot` | `aurora_agent` |
| `org.aurora.agent:handlers/react/execute_tools/execute` | `hook_handler` | `aurora_agent` |
| `org.aurora.agent:handlers/react/interpret_response` | `component` | `aurora_agent` |
| `org.aurora.agent:handlers/react/interpret_response/execute` | `hook_handler` | `aurora_agent` |
| `org.aurora.agent:handlers/react/record_observation` | `component` | `aurora_agent` |
| `org.aurora.agent:handlers/react/record_observation/execute` | `hook_handler` | `aurora_agent` |
| `org.aurora.agent:handlers/react_agent` | `component` | `aurora_agent` |
| `org.aurora.agent:handlers/react_agent/execute` | `hook_handler` | `aurora_agent` |
| `org.aurora.agent:react/act` | `hook_slot` | `aurora_agent` |
| `org.aurora.agent:react/error` | `hook_slot` | `aurora_agent` |
| `org.aurora.agent:react/finish` | `hook_slot` | `aurora_agent` |
| `org.aurora.agent:react/infer` | `hook_slot` | `aurora_agent` |
| `org.aurora.agent:react/observe` | `hook_slot` | `aurora_agent` |
| `org.aurora.agent:react/prepare` | `hook_slot` | `aurora_agent` |
| `org.aurora.agent:registries/tools` | `registry` | `aurora_agent` |
| `org.aurora.agent:tools/after_call` | `hook_slot` | `aurora_agent` |
| `org.aurora.agent:tools/before_call` | `hook_slot` | `aurora_agent` |

### org.aurora.api

| ID | kind | provider |
| --- | --- | --- |
| `org.aurora.api:registries/endpoints` | `registry` | `aurora_api` |

### org.aurora.bot

| ID | kind | provider |
| --- | --- | --- |
| `org.aurora.bot:assemblies/default` | `assembly` | `aurora_bot` |
| `org.aurora.bot:commands/run/activate` | `command` | `aurora_bot` |
| `org.aurora.bot:commands/run/cancel` | `command` | `aurora_bot` |
| `org.aurora.bot:commands/run/submit` | `command` | `aurora_bot` |
| `org.aurora.bot:components/actions/read` | `component` | `aurora_bot` |
| `org.aurora.bot:components/actions/read/execute` | `hook_handler` | `aurora_bot` |
| `org.aurora.bot:components/memory` | `component` | `aurora_bot.memory` |
| `org.aurora.bot:components/memory/execute` | `hook_handler` | `aurora_bot.memory` |
| `org.aurora.bot:components/notes` | `component` | `aurora_bot` |
| `org.aurora.bot:components/notes/execute` | `hook_handler` | `aurora_bot` |
| `org.aurora.bot:components/self_control` | `component` | `aurora_bot` |
| `org.aurora.bot:components/self_control/execute` | `hook_handler` | `aurora_bot` |
| `org.aurora.bot:components/world/read_event` | `component` | `aurora_bot` |
| `org.aurora.bot:components/world/read_event/execute` | `hook_handler` | `aurora_bot` |
| `org.aurora.bot:configs/cadence` | `config` | `aurora_bot.cadence` |
| `org.aurora.bot:configs/default` | `config` | `aurora_bot` |
| `org.aurora.bot:configs/memory` | `config` | `aurora_bot.memory` |
| `org.aurora.bot:endpoints/conversation` | `endpoint` | `aurora_bot` |
| `org.aurora.bot:handlers/assembly/clean_bot` | `hook_handler` | `aurora_bot` |
| `org.aurora.bot:handlers/assembly/clean_model` | `hook_handler` | `aurora_bot` |
| `org.aurora.bot:handlers/assembly/prepare_bot` | `hook_handler` | `aurora_bot` |
| `org.aurora.bot:handlers/assembly/prepare_model` | `hook_handler` | `aurora_bot` |
| `org.aurora.bot:handlers/assembly/start_bot` | `hook_handler` | `aurora_bot` |
| `org.aurora.bot:handlers/assembly/stop_bot` | `hook_handler` | `aurora_bot` |
| `org.aurora.bot:handlers/cadence/clean` | `hook_handler` | `aurora_bot.cadence` |
| `org.aurora.bot:handlers/cadence/prepare` | `hook_handler` | `aurora_bot.cadence` |
| `org.aurora.bot:handlers/cadence/start` | `hook_handler` | `aurora_bot.cadence` |
| `org.aurora.bot:handlers/cadence/stop` | `hook_handler` | `aurora_bot.cadence` |
| `org.aurora.bot:operations/run/activate` | `operation` | `aurora_bot` |
| `org.aurora.bot:operations/run/cancel` | `operation` | `aurora_bot` |
| `org.aurora.bot:operations/run/submit` | `operation` | `aurora_bot` |
| `org.aurora.bot:services/run_control` | `service` | `aurora_bot` |
| `org.aurora.bot:state/agents` | `state_key` | `aurora_bot` |
| `org.aurora.bot:state/cadence` | `state_key` | `aurora_bot.cadence` |
| `org.aurora.bot:state/cadence_config` | `state_key` | `aurora_bot.cadence` |
| `org.aurora.bot:state/config` | `state_key` | `aurora_bot` |
| `org.aurora.bot:state/memory/config` | `state_key` | `aurora_bot.memory` |
| `org.aurora.bot:state/messages` | `state_key` | `aurora_bot` |
| `org.aurora.bot:state/notes` | `state_key` | `aurora_bot` |
| `org.aurora.bot:state/react_work` | `state_key` | `aurora_bot` |
| `org.aurora.bot:state/run` | `state_key` | `aurora_bot` |
| `org.aurora.bot:state/self_control` | `state_key` | `aurora_bot` |
| `org.aurora.bot:tools/actions/read` | `tool` | `aurora_bot` |
| `org.aurora.bot:tools/memory/delete` | `tool` | `aurora_bot.memory` |
| `org.aurora.bot:tools/memory/read` | `tool` | `aurora_bot.memory` |
| `org.aurora.bot:tools/memory/reindex` | `tool` | `aurora_bot.memory` |
| `org.aurora.bot:tools/memory/search` | `tool` | `aurora_bot.memory` |
| `org.aurora.bot:tools/memory/write` | `tool` | `aurora_bot.memory` |
| `org.aurora.bot:tools/notes/list` | `tool` | `aurora_bot` |
| `org.aurora.bot:tools/notes/read` | `tool` | `aurora_bot` |
| `org.aurora.bot:tools/notes/write` | `tool` | `aurora_bot` |
| `org.aurora.bot:tools/self_control/autonomy` | `tool` | `aurora_bot` |
| `org.aurora.bot:tools/self_control/cancel` | `tool` | `aurora_bot` |
| `org.aurora.bot:tools/self_control/finish` | `tool` | `aurora_bot` |
| `org.aurora.bot:tools/self_control/list` | `tool` | `aurora_bot` |
| `org.aurora.bot:tools/self_control/schedule` | `tool` | `aurora_bot` |
| `org.aurora.bot:tools/self_control/status` | `tool` | `aurora_bot` |
| `org.aurora.bot:tools/world/read_event` | `tool` | `aurora_bot` |

### org.aurora.cli

| ID | kind | provider |
| --- | --- | --- |
| `org.aurora.cli:commands/about` | `command` | `aurora_cli.commands.about` |
| `org.aurora.cli:commands/bot` | `command` | `aurora_cli.commands.launch` |
| `org.aurora.cli:commands/check` | `command` | `aurora_cli.commands.check` |
| `org.aurora.cli:commands/ctx/delete` | `command` | `aurora_cli.commands.ctx` |
| `org.aurora.cli:commands/ctx/get` | `command` | `aurora_cli.commands.ctx` |
| `org.aurora.cli:commands/ctx/list` | `command` | `aurora_cli.commands.ctx` |
| `org.aurora.cli:commands/ctx/set` | `command` | `aurora_cli.commands.ctx` |
| `org.aurora.cli:commands/ctx/watch` | `command` | `aurora_cli.commands.ctx` |
| `org.aurora.cli:commands/donk/major` | `command` | `aurora_cli.commands.donk` |
| `org.aurora.cli:commands/donk/minor` | `command` | `aurora_cli.commands.donk` |
| `org.aurora.cli:commands/donk/patch` | `command` | `aurora_cli.commands.donk` |
| `org.aurora.cli:commands/donk/show` | `command` | `aurora_cli.commands.donk` |
| `org.aurora.cli:commands/help` | `command` | `aurora_cli.commands.help` |
| `org.aurora.cli:commands/id/list` | `command` | `aurora_cli.commands.id` |
| `org.aurora.cli:commands/panel` | `command` | `aurora_cli.commands.launch` |
| `org.aurora.cli:commands/run` | `command` | `aurora_cli.commands.run` |
| `org.aurora.cli:commands/serve` | `command` | `aurora_cli.commands.serve` |
| `org.aurora.cli:commands/tui` | `command` | `aurora_cli.commands.launch` |
| `org.aurora.cli:configs/default` | `config` | `aurora_cli` |
| `org.aurora.cli:registries/commands` | `registry` | `aurora_cli` |
| `org.aurora.cli:schemas/command` | `schema` | `aurora_cli` |
| `org.aurora.cli:state/config` | `state_key` | `aurora_cli` |

### org.aurora.config

| ID | kind | provider |
| --- | --- | --- |
| `org.aurora.config:endpoints/configuration` | `endpoint` | `aurora_config` |
| `org.aurora.config:handlers/load` | `hook_handler` | `aurora_config` |
| `org.aurora.config:registries/configs` | `registry` | `aurora_config` |

### org.aurora.control

| ID | kind | provider |
| --- | --- | --- |
| `org.aurora.control:handlers/control` | `component` | `aurora_control` |
| `org.aurora.control:handlers/control/branch` | `component` | `aurora_control` |
| `org.aurora.control:handlers/control/branch/children` | `hook_slot` | `aurora_control` |
| `org.aurora.control:handlers/control/branch/execute` | `hook_handler` | `aurora_control` |
| `org.aurora.control:handlers/control/children` | `hook_slot` | `aurora_control` |
| `org.aurora.control:handlers/control/execute` | `hook_handler` | `aurora_control` |
| `org.aurora.control:handlers/control/parallel` | `component` | `aurora_control` |
| `org.aurora.control:handlers/control/parallel/children` | `hook_slot` | `aurora_control` |
| `org.aurora.control:handlers/control/parallel/execute` | `hook_handler` | `aurora_control` |
| `org.aurora.control:handlers/control/serial` | `component` | `aurora_control` |
| `org.aurora.control:handlers/control/serial/children` | `hook_slot` | `aurora_control` |
| `org.aurora.control:handlers/control/serial/execute` | `hook_handler` | `aurora_control` |
| `org.aurora.control:handlers/control/while` | `component` | `aurora_control` |
| `org.aurora.control:handlers/control/while/children` | `hook_slot` | `aurora_control` |
| `org.aurora.control:handlers/control/while/execute` | `hook_handler` | `aurora_control` |
| `org.aurora.control:state/control` | `state_key` | `aurora_control` |

### org.aurora.core

| ID | kind | provider |
| --- | --- | --- |
| `org.aurora.core:events/ctx/changed` | `event` | `aurora_core` |
| `org.aurora.core:operations/ctx/delete` | `operation` | `aurora_core` |
| `org.aurora.core:operations/ctx/get` | `operation` | `aurora_core` |
| `org.aurora.core:operations/ctx/list` | `operation` | `aurora_core` |
| `org.aurora.core:operations/ctx/set` | `operation` | `aurora_core` |
| `org.aurora.core:operations/ctx/subscribe` | `operation` | `aurora_core` |
| `org.aurora.core:operations/ctx/unsubscribe` | `operation` | `aurora_core` |
| `org.aurora.core:lifecycle/clean` | `hook_slot` | `aurora_core` |
| `org.aurora.core:lifecycle/config` | `hook_slot` | `aurora_core` |
| `org.aurora.core:lifecycle/prepare` | `hook_slot` | `aurora_core` |
| `org.aurora.core:lifecycle/start` | `hook_slot` | `aurora_core` |
| `org.aurora.core:lifecycle/stop` | `hook_slot` | `aurora_core` |
| `org.aurora.core:registries/events` | `registry` | `aurora_core` |
| `org.aurora.core:registries/hook_handlers` | `registry` | `aurora_core` |
| `org.aurora.core:registries/hook_slots` | `registry` | `aurora_core` |
| `org.aurora.core:registries/operations` | `registry` | `aurora_core` |
| `org.aurora.core:registries/plugins` | `registry` | `aurora_core` |
| `org.aurora.core:registries/registries` | `registry` | `aurora_core` |
| `org.aurora.core:registries/resources` | `registry` | `aurora_core` |
| `org.aurora.core:registries/schemas` | `registry` | `aurora_core` |
| `org.aurora.core:registries/services` | `registry` | `aurora_core` |
| `org.aurora.core:registries/state_keys` | `registry` | `aurora_core` |

### org.aurora.world

| ID | kind | provider |
| --- | --- | --- |
| `org.aurora.world:configs/sources` | `config` | `aurora_world.configuration` |
| `org.aurora.world:handlers/records/clean` | `hook_handler` | `aurora_world` |
| `org.aurora.world:handlers/records/prepare` | `hook_handler` | `aurora_world` |
| `org.aurora.world:handlers/records/start` | `hook_handler` | `aurora_world` |
| `org.aurora.world:handlers/records/stop` | `hook_handler` | `aurora_world` |
| `org.aurora.world:handlers/sources/clean` | `hook_handler` | `aurora_world` |
| `org.aurora.world:handlers/sources/configure` | `hook_handler` | `aurora_world.configuration` |
| `org.aurora.world:handlers/sources/prepare` | `hook_handler` | `aurora_world` |
| `org.aurora.world:handlers/sources/start` | `hook_handler` | `aurora_world` |
| `org.aurora.world:handlers/sources/stop` | `hook_handler` | `aurora_world` |
| `org.aurora.world:registries/sources` | `registry` | `aurora_world` |
| `org.aurora.world:sources/environment/time` | `source` | `aurora_world.environment` |
| `org.aurora.world:sources/environment/weather` | `source` | `aurora_world.environment` |
| `org.aurora.world:state/config` | `state_key` | `aurora_world.configuration` |
| `org.aurora.world:state/environment` | `state_key` | `aurora_world` |
| `org.aurora.world:state/records` | `state_key` | `aurora_world` |
| `org.aurora.world:state/sources` | `state_key` | `aurora_world` |

## 核对入口

按用户实际插件选择查询：`uv run --locked aurora --data-dir build/onboarding id list`。该数据目录应先由助手 --init 初始化；仅查询登记，不启动装配。完整仓库清单额外包含此用户预设没有启用的插件。

配置、端点和运行约束见[配置指南](configuration.md)、[操作指南](operations.md)和[当前架构](aurorabot-design-v0.2.3.md)。变更 ID 或插件名时说明配置与快照影响，不自动删除旧状态或添加未经要求的别名。
