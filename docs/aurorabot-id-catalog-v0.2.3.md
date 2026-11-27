# AuroraBot 公共 ID 与组件目录

核对基线：W08（2026-11-27）。本页从工作区各发行包 `plugin.meta.json` 汇总：**29 个公开插件、core/CLI 两个宿主目录、225 个静态定义**。生成目录来自各插件清单与契约；汇总不导入插件、不创建资源。文件名保留以维持引用，旧设计见[历史归档](archive/2026-11-09/aurorabot-id-catalog-v0.2.3.md)。

## 身份与查询

ID 格式为 `<namespace>:<domain>/<local_path>`。定义存在不表示插件已启用、实例已创建、插头已连接或端点已开放。定义 ID、实例身份、run_id 和 execution_id 分开管理；ctx 由状态 ID 与精确 location 寻址，namespace 不构成同进程权限隔离。

`aurora-meta catalog aurora-agent` 可读取已安装发行的静态目录；`aurora --data-dir build/onboarding id list` 列出已初始化装配所选择插件的运行定义。独立 CLI 计划/实际图查询尚未提供。MCP 动态工具要在 prepare 读取目录后才出现，不计入静态定义总数。

## 公开插件

requires 只校验显式启用依赖，不隐式加载。每个链接指向该插件的唯一清单。

| 插件入口 / Plugin.name | requires | 职责与清单 |
| --- | --- | --- |
| `aurora_agent.configuration` | `aurora_config`、`aurora_agent.react`、`aurora_agent.model`、`aurora_agent.react_defaults` | [按实际消费者登记非持久配置；不创建业务实例](../packages/aurora_agent/src/aurora_agent/plugins/configuration/plugin.meta.toml) |
| `aurora_agent.model` | — | [读取请求状态，调用绑定的模型资源并更新输出状态](../packages/aurora_agent/src/aurora_agent/plugins/model/plugin.meta.toml) |
| `aurora_agent.react` | — | [ReAct 执行的公开定义与真实实例导出](../packages/aurora_agent/src/aurora_agent/plugins/react/plugin.meta.toml) |
| `aurora_agent.react_defaults` | `aurora_agent.react`、`aurora_agent.model`、`aurora_tools` | [ReAct 默认阶段的公开定义与真实实例导出](../packages/aurora_agent/src/aurora_agent/plugins/defaults/plugin.meta.toml) |
| `aurora_api` | — | [接收显式选用的 HTTP 端点，不分发任意操作](../packages/aurora_api/src/aurora_api/plugin.meta.toml) |
| `aurora_bot.actions` | `aurora_tools`、`aurora_config` | [导出本能力的定义、端口和资源，由宿主显式装配](../packages/aurora_bot/src/aurora_bot/plugins/actions/plugin.meta.toml) |
| `aurora_bot.cadence` | `aurora_bot.runtime`、`aurora_world.records`、`aurora_config` | [导出本能力的定义、端口和资源，由宿主显式装配](../packages/aurora_bot/src/aurora_bot/plugins/cadence/plugin.meta.toml) |
| `aurora_bot.commands` | `aurora_bot.runtime` | [导出本能力的定义、端口和资源，由宿主显式装配](../packages/aurora_bot/src/aurora_bot/plugins/commands/plugin.meta.toml) |
| `aurora_bot.conversation` | `aurora_bot.runtime` | [导出本能力的定义、端口和资源，由宿主显式装配](../packages/aurora_bot/src/aurora_bot/plugins/conversation/plugin.meta.toml) |
| `aurora_bot.notes` | `aurora_tools` | [导出本能力的定义、端口和资源，由宿主显式装配](../packages/aurora_bot/src/aurora_bot/plugins/notes/plugin.meta.toml) |
| `aurora_bot.runtime` | `aurora_agent.react` | [导出本能力的定义、端口和资源，由宿主显式装配](../packages/aurora_bot/src/aurora_bot/plugins/runtime/plugin.meta.toml) |
| `aurora_bot.self_control` | `aurora_bot.runtime`、`aurora_tools` | [导出本能力的定义、端口和资源，由宿主显式装配](../packages/aurora_bot/src/aurora_bot/plugins/self_control/plugin.meta.toml) |
| `aurora_bot.world_view` | `aurora_world.records`、`aurora_tools`、`aurora_config` | [导出本能力的定义、端口和资源，由宿主显式装配](../packages/aurora_bot/src/aurora_bot/plugins/world_view/plugin.meta.toml) |
| `aurora_config` | — | [加载已登记的 TOML 配置，完成校验并注入 ctx](../packages/aurora_config/src/aurora_config/plugin.meta.toml) |
| `aurora_control` | — | [通过实例端口和状态绑定组合执行](../packages/aurora_control/src/aurora_control/plugin.meta.toml) |
| `aurora_mcp` | `aurora_config` | [MCP 客户端的公开定义与真实实例导出](../packages/aurora_mcp/src/aurora_mcp/plugins/clients/plugin.meta.toml) |
| `aurora_mcp.tools` | `aurora_mcp`、`aurora_tools` | [MCP 工具目录的公开定义与真实实例导出](../packages/aurora_mcp/src/aurora_mcp/plugins/tools/plugin.meta.toml) |
| `aurora_mcp.world` | `aurora_mcp`、`aurora_world.sources` | [MCP 世界来源的公开定义与真实实例导出](../packages/aurora_mcp/src/aurora_mcp/plugins/world/plugin.meta.toml) |
| `aurora_memory` | `aurora_config`、`aurora_tools` | [owner 隔离的存储与五种工具；借用显式 embedding 资源](../packages/aurora_memory/src/aurora_memory/plugin.meta.toml) |
| `aurora_memory.compaction` | `aurora_memory` | [先归档原文，再异步索引摘要；只借用记忆存储](../packages/aurora_memory/src/aurora_memory/compaction/plugin.meta.toml) |
| `aurora_model` | — | [模型协议与资源的公开定义与真实实例导出](../packages/aurora_model/src/aurora_model/plugins/model/plugin.meta.toml) |
| `aurora_model.configuration` | `aurora_model`、`aurora_config` | [模型配置的公开定义与真实实例导出](../packages/aurora_model/src/aurora_model/plugins/configuration/plugin.meta.toml) |
| `aurora_model.litellm` | `aurora_model` | [LiteLLM 供应商的公开定义与真实实例导出](../packages/aurora_model/src/aurora_model/plugins/litellm/plugin.meta.toml) |
| `aurora_tools` | — | [工具执行与集合的公开定义与真实实例导出](../packages/aurora_tools/src/aurora_tools/plugins/tools/plugin.meta.toml) |
| `aurora_tools.configuration` | `aurora_config`、`aurora_tools` | [按实际消费者登记非持久配置；不创建业务实例](../packages/aurora_tools/src/aurora_tools/plugins/configuration/plugin.meta.toml) |
| `aurora_world.configuration` | `aurora_config`、`aurora_world.records`、`aurora_world.sources` | [声明来源选择与视图参数，在 config 阶段配置已绑定的来源所有者](../packages/aurora_world/src/aurora_world/plugins/configuration/plugin.meta.toml) |
| `aurora_world.environment` | `aurora_world.sources` | [提供时间与天气观察工厂，实例创建时才初始化外部资源](../packages/aurora_world/src/aurora_world/plugins/environment/plugin.meta.toml) |
| `aurora_world.records` | — | [归档世界事件并维护有界 ctx 视图，不创建世界来源](../packages/aurora_world/src/aurora_world/plugins/records/plugin.meta.toml) |
| `aurora_world.sources` | `aurora_world.records` | [选择来源工厂、管理任务与接纳入口，借用记录服务](../packages/aurora_world/src/aurora_world/plugins/sources/plugin.meta.toml) |

## 按发行包查询定义与端口

每个组件的插头/插槽以下列完整 ID 为准，状态和资源列为局部角色名；问号表示可选，资源映射单列。契约、参数 schema 与纯导出链接在对应清单中，本文不复制 schema。资源引用不等于执行接线，实际实例关系由[完整预设](configuration.md#选择完整预设)决定。

### aurora-agent

[发行静态目录](../packages/aurora_agent/plugin.meta.json)

#### aurora_agent.model

[源清单](../packages/aurora_agent/src/aurora_agent/plugins/model/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.agent:handlers/model_call` | `component` | `MODEL_CALL` | 模型调用组件 |
| `org.aurora.agent:handlers/model_call/execute` | `hook_handler` | `EXECUTE` | 模型执行插头 |
| `org.aurora.agent:handlers/model_call/configure` | `hook_handler` | `CONFIGURE` | 读取显式绑定的模型调用参数 |

组件 `model_call`：模型客户端由资源绑定提供，组件不关闭借用的客户端

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.agent:handlers/model_call/execute`、`org.aurora.agent:handlers/model_call/configure` |
| 插槽 | — |
| 状态 | `input`、`output`、`config?` |
| 借用资源 | `chat` |
| 导出资源 | `model_call` |
| 资源映射 | — |
| 参数契约 | `model_options` |

#### aurora_agent.react

[源清单](../packages/aurora_agent/src/aurora_agent/plugins/react/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.agent:handlers/react_agent` | `component` | `REACT` | 可重复激活的 ReAct 组件 |
| `org.aurora.agent:handlers/react_agent/execute` | `hook_handler` | `EXECUTE` | 执行实例的一次调用 |
| `org.aurora.agent:react/prepare` | `hook_slot` | `PREPARE` | 准备阶段端口 |
| `org.aurora.agent:react/infer` | `hook_slot` | `INFER` | 推理阶段执行槽 |
| `org.aurora.agent:react/act` | `hook_slot` | `ACT` | 行动阶段执行槽 |
| `org.aurora.agent:react/observe` | `hook_slot` | `OBSERVE` | 观察阶段执行槽 |
| `org.aurora.agent:react/finish` | `hook_slot` | `FINISH` | 完成阶段执行槽 |
| `org.aurora.agent:react/error` | `hook_slot` | `ERROR` | 错误阶段执行槽 |
| `org.aurora.agent:handlers/react/configure` | `hook_handler` | `CONFIGURE` | 读取显式绑定的 ReAct 参数 |

组件 `react`：

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.agent:handlers/react_agent/execute`、`org.aurora.agent:handlers/react/configure` |
| 插槽 | `org.aurora.agent:react/prepare`、`org.aurora.agent:react/infer`、`org.aurora.agent:react/act`、`org.aurora.agent:react/observe`、`org.aurora.agent:react/finish`、`org.aurora.agent:react/error` |
| 状态 | `inbox`、`progress`、`runtime`、`batch`、`decision`、`config?` |
| 借用资源 | — |
| 导出资源 | `agent` |
| 资源映射 | — |
| 参数契约 | `options` |

#### aurora_agent.react_defaults

[源清单](../packages/aurora_agent/src/aurora_agent/plugins/defaults/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.agent:handlers/react/build_prompt` | `component` | `BUILD_PROMPT` | 准备模型上下文的默认阶段 |
| `org.aurora.agent:handlers/react/build_prompt/execute` | `hook_handler` | `BUILD_PROMPT_EXECUTE` | 把引导和历史写入模型请求状态 |
| `org.aurora.agent:handlers/react/interpret_response` | `component` | `INTERPRET_RESPONSE` | 解释模型响应的默认阶段 |
| `org.aurora.agent:handlers/react/interpret_response/execute` | `hook_handler` | `INTERPRET_RESPONSE_EXECUTE` | 把模型响应转换为行动或完成决定 |
| `org.aurora.agent:handlers/react/record_observation` | `component` | `RECORD_OBSERVATION` | 接纳工具观察的默认阶段 |
| `org.aurora.agent:handlers/react/record_observation/execute` | `hook_handler` | `RECORD_OBSERVATION_EXECUTE` | 把工具批次结果追加到上下文 |
| `org.aurora.agent:handlers/react_defaults/configure` | `hook_handler` | `CONFIGURE` | 读取显式绑定的提示词参数 |
| `org.aurora.agent:handlers/input_budget/configure` | `hook_handler` | `BUDGET_CONFIGURE` | 读取显式绑定的参数 |
| `org.aurora.agent:handlers/compaction/configure` | `hook_handler` | `COMPACTION_CONFIGURE` | 读取显式绑定的参数 |

组件 `defaults`：

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.agent:handlers/react/build_prompt/execute`、`org.aurora.agent:handlers/react/interpret_response/execute`、`org.aurora.agent:handlers/react/record_observation/execute`、`org.aurora.agent:handlers/react_defaults/configure` |
| 插槽 | — |
| 状态 | `context`、`batch`、`decision`、`model_input`、`model_output`、`tool_input`、`tool_output`、`config?` |
| 借用资源 | `agent`、`tools`、`context_view?`、`input_budget?`、`compactor?`、`tool_observation?` |
| 导出资源 | `defaults` |
| 资源映射 | — |
| 参数契约 | `options` |

组件 `input_budget`：

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.agent:handlers/input_budget/configure` |
| 插槽 | — |
| 状态 | `config?` |
| 借用资源 | — |
| 导出资源 | `input_budget` |
| 资源映射 | — |
| 参数契约 | `input_budget` |

组件 `compaction`：

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.agent:handlers/compaction/configure` |
| 插槽 | — |
| 状态 | `config?` |
| 借用资源 | `chat`、`budget`、`recorder?` |
| 导出资源 | `compaction` |
| 资源映射 | — |
| 参数契约 | `compaction` |

#### aurora_agent.configuration

[源清单](../packages/aurora_agent/src/aurora_agent/plugins/configuration/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.agent:configs/react` | `config` | `REACT` | react 的行为参数 |
| `org.aurora.agent:state/react/config` | `state_key` | `REACT_STATE` | react 的非持久配置状态 |
| `org.aurora.agent:configs/model_call` | `config` | `MODEL_CALL` | model_call 的行为参数 |
| `org.aurora.agent:state/model_call/config` | `state_key` | `MODEL_CALL_STATE` | model_call 的非持久配置状态 |
| `org.aurora.agent:configs/react_defaults` | `config` | `REACT_DEFAULTS` | react_defaults 的行为参数 |
| `org.aurora.agent:state/react_defaults/config` | `state_key` | `REACT_DEFAULTS_STATE` | react_defaults 的非持久配置状态 |
| `org.aurora.agent:configs/input_budget` | `config` | `INPUT_BUDGET` | input_budget 的行为参数 |
| `org.aurora.agent:state/input_budget/config` | `state_key` | `INPUT_BUDGET_STATE` | input_budget 的非持久配置状态 |
| `org.aurora.agent:configs/compaction` | `config` | `COMPACTION` | compaction 的行为参数 |
| `org.aurora.agent:state/compaction/config` | `state_key` | `COMPACTION_STATE` | compaction 的非持久配置状态 |

### aurora-api

[发行静态目录](../packages/aurora_api/plugin.meta.json)

#### aurora_api

[源清单](../packages/aurora_api/src/aurora_api/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.api:registries/endpoints` | `registry` | `ENDPOINTS` | HTTP 端点接收方 |

### aurora-bot

[发行静态目录](../packages/aurora_bot/plugin.meta.json)

#### aurora_bot.runtime

[源清单](../packages/aurora_bot/src/aurora_bot/plugins/runtime/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.bot:services/run_control` | `service` | `RUN_CONTROL` | 按产品实例定位运行管理器 |
| `org.aurora.bot:operations/run/submit` | `operation` | `RUN_SUBMIT` | 向实例提交引导并返回运行回执 |
| `org.aurora.bot:operations/run/activate` | `operation` | `RUN_ACTIVATE` | 显式激活实例 |
| `org.aurora.bot:operations/run/cancel` | `operation` | `RUN_CANCEL` | 取消匹配运行并等待收尾 |
| `org.aurora.bot:state/agents` | `state_key` | `AGENTS` | 实例引导队列与接纳进度 |
| `org.aurora.bot:state/messages` | `state_key` | `MESSAGES` | 实例交流上下文 |
| `org.aurora.bot:state/run` | `state_key` | `RUN` | 实例运行状态 |
| `org.aurora.bot:state/react_work` | `state_key` | `WORK` | 按运行隔离的产品工作状态 |
| `org.aurora.bot:handlers/runtime/prepare` | `hook_handler` | `PREPARE` | 将恢复的未完成状态标记为中断 |
| `org.aurora.bot:handlers/runtime/start` | `hook_handler` | `START` | 启动自有调度器并绑定运行操作 |
| `org.aurora.bot:handlers/runtime/stop` | `hook_handler` | `STOP` | 等待自有运行结束并裁剪工作状态 |
| `org.aurora.bot:handlers/runtime/clean` | `hook_handler` | `CLEAN` | 解除本实例的运行操作绑定 |

组件 `operations`：

| 角色 | 声明 |
| --- | --- |
| 插头 | — |
| 插槽 | — |
| 状态 | — |
| 借用资源 | — |
| 导出资源 | `operations` |
| 资源映射 | — |

组件 `runtime`：

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.bot:handlers/runtime/prepare`、`org.aurora.bot:handlers/runtime/start`、`org.aurora.bot:handlers/runtime/stop`、`org.aurora.bot:handlers/runtime/clean` |
| 插槽 | — |
| 状态 | `context`、`model_output`、`tool_output`、`work` |
| 借用资源 | `agent`、`operations` |
| 导出资源 | `runtime`、`owner` |
| 资源映射 | — |
| 参数契约 | `owner` |

#### aurora_bot.conversation

[源清单](../packages/aurora_bot/src/aurora_bot/plugins/conversation/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.bot:endpoints/conversation` | `endpoint` | `CONVERSATION` | 直接交流入口 |

组件 `endpoint`：

| 角色 | 声明 |
| --- | --- |
| 插头 | — |
| 插槽 | — |
| 状态 | — |
| 借用资源 | `operations` |
| 导出资源 | `endpoint` |
| 资源映射 | — |

#### aurora_bot.commands

[源清单](../packages/aurora_bot/src/aurora_bot/plugins/commands/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.bot:commands/run/submit` | `command` | `SUBMIT` | 运行命令 |
| `org.aurora.bot:commands/run/activate` | `command` | `ACTIVATE` | 运行命令 |
| `org.aurora.bot:commands/run/cancel` | `command` | `CANCEL` | 运行命令 |

#### aurora_bot.notes

[源清单](../packages/aurora_bot/src/aurora_bot/plugins/notes/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.bot:state/notes` | `state_key` | `NOTES` | 本能力持有的状态 |
| `org.aurora.bot:components/notes` | `component` | `COMPONENT` | 工具执行组件 |
| `org.aurora.bot:components/notes/execute` | `hook_handler` | `EXECUTE` | 公开方法插头 |
| `org.aurora.bot:tools/notes/write` | `tool` | `WRITE` | 显式选择的工具 |
| `org.aurora.bot:tools/notes/read` | `tool` | `READ` | 显式选择的工具 |
| `org.aurora.bot:tools/notes/list` | `tool` | `LIST` | 显式选择的工具 |

组件 `notes`：

| 角色 | 声明 |
| --- | --- |
| 插头 | — |
| 插槽 | — |
| 状态 | — |
| 借用资源 | — |
| 导出资源 | `notes` |
| 资源映射 | — |
| 参数契约 | `owner` |

#### aurora_bot.actions

[源清单](../packages/aurora_bot/src/aurora_bot/plugins/actions/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.bot:components/actions/read` | `component` | `COMPONENT` | 工具执行组件 |
| `org.aurora.bot:components/actions/read/execute` | `hook_handler` | `EXECUTE` | 公开方法插头 |
| `org.aurora.bot:tools/actions/read` | `tool` | `READ_ACTION` | 显式选择的工具 |
| `org.aurora.bot:handlers/actions/prepare` | `hook_handler` | `PREPARE` | 公开方法插头 |
| `org.aurora.bot:handlers/actions/clean` | `hook_handler` | `CLEAN` | 公开方法插头 |
| `org.aurora.bot:configs/actions` | `config` | `CONFIGURATION` | 业务参数配置 |
| `org.aurora.bot:state/actions/config` | `state_key` | `CONFIG_STATE` | 本能力持有的状态 |

组件 `actions`：

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.bot:handlers/actions/prepare`、`org.aurora.bot:handlers/actions/clean` |
| 插槽 | — |
| 状态 | `config?`、`observation_config?` |
| 借用资源 | — |
| 导出资源 | `evidence`、`observation` |
| 资源映射 | — |
| 参数契约 | `owner` |

#### aurora_bot.self_control

[源清单](../packages/aurora_bot/src/aurora_bot/plugins/self_control/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.bot:state/self_control` | `state_key` | `SELF_CONTROL` | 本能力持有的状态 |
| `org.aurora.bot:components/self_control` | `component` | `COMPONENT` | 工具执行组件 |
| `org.aurora.bot:components/self_control/execute` | `hook_handler` | `EXECUTE` | 公开方法插头 |
| `org.aurora.bot:tools/self_control/status` | `tool` | `STATUS` | 显式选择的工具 |
| `org.aurora.bot:tools/self_control/autonomy` | `tool` | `AUTONOMY` | 显式选择的工具 |
| `org.aurora.bot:tools/self_control/finish` | `tool` | `FINISH` | 显式选择的工具 |
| `org.aurora.bot:tools/self_control/schedule` | `tool` | `SCHEDULE` | 显式选择的工具 |
| `org.aurora.bot:tools/self_control/list` | `tool` | `LIST` | 显式选择的工具 |
| `org.aurora.bot:tools/self_control/cancel` | `tool` | `CANCEL` | 显式选择的工具 |
| `org.aurora.bot:handlers/self_control/prepare` | `hook_handler` | `PREPARE` | 公开方法插头 |
| `org.aurora.bot:handlers/self_control/start` | `hook_handler` | `START` | 公开方法插头 |
| `org.aurora.bot:handlers/self_control/clean` | `hook_handler` | `CLEAN` | 公开方法插头 |

组件 `control`：

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.bot:handlers/self_control/prepare`、`org.aurora.bot:handlers/self_control/start`、`org.aurora.bot:handlers/self_control/clean` |
| 插槽 | — |
| 状态 | — |
| 借用资源 | `runtime`、`agent` |
| 导出资源 | `control` |
| 资源映射 | — |
| 参数契约 | `owner` |

#### aurora_bot.world_view

[源清单](../packages/aurora_bot/src/aurora_bot/plugins/world_view/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.bot:components/world/read_event` | `component` | `COMPONENT` | 工具执行组件 |
| `org.aurora.bot:components/world/read_event/execute` | `hook_handler` | `EXECUTE` | 公开方法插头 |
| `org.aurora.bot:tools/world/read_event` | `tool` | `READ_EVENT` | 显式选择的工具 |
| `org.aurora.bot:handlers/world_view/prepare` | `hook_handler` | `PREPARE` | 公开方法插头 |
| `org.aurora.bot:configs/world_view` | `config` | `CONFIGURATION` | 业务参数配置 |
| `org.aurora.bot:state/world_view/config` | `state_key` | `CONFIG_STATE` | 本能力持有的状态 |

组件 `view`：

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.bot:handlers/world_view/prepare` |
| 插槽 | — |
| 状态 | `config?` |
| 借用资源 | `records?`、`notes?`、`actions?`、`archive?` |
| 导出资源 | `view` |
| 资源映射 | — |
| 参数契约 | `options` |

组件 `archive`：

| 角色 | 声明 |
| --- | --- |
| 插头 | — |
| 插槽 | — |
| 状态 | `config?` |
| 借用资源 | `records` |
| 导出资源 | `archive` |
| 资源映射 | — |

#### aurora_bot.cadence

[源清单](../packages/aurora_bot/src/aurora_bot/plugins/cadence/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.bot:configs/cadence` | `config` | `CONFIGURATION` | 业务参数配置 |
| `org.aurora.bot:state/cadence` | `state_key` | `CHECKPOINT` | 本能力持有的状态 |
| `org.aurora.bot:handlers/cadence/prepare` | `hook_handler` | `PREPARE` | 公开方法插头 |
| `org.aurora.bot:handlers/cadence/start` | `hook_handler` | `START` | 公开方法插头 |
| `org.aurora.bot:handlers/cadence/stop` | `hook_handler` | `STOP` | 公开方法插头 |
| `org.aurora.bot:handlers/cadence/clean` | `hook_handler` | `CLEAN` | 公开方法插头 |
| `org.aurora.bot:state/cadence_config` | `state_key` | `CONFIG_STATE` | 本能力持有的状态 |

组件 `cadence`：

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.bot:handlers/cadence/prepare`、`org.aurora.bot:handlers/cadence/start`、`org.aurora.bot:handlers/cadence/stop`、`org.aurora.bot:handlers/cadence/clean` |
| 插槽 | — |
| 状态 | — |
| 借用资源 | `runtime`、`records`、`choice?`、`view?`、`control?` |
| 导出资源 | `cadence` |
| 资源映射 | — |
| 参数契约 | `owner` |

### aurora-cli

[发行静态目录](../packages/aurora_cli/plugin.meta.json)

#### aurora_cli（宿主）

[源清单](../packages/aurora_cli/src/aurora_cli/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.cli:registries/commands` | `registry` | `COMMANDS` | CLI registries/commands |
| `org.aurora.cli:schemas/command` | `schema` | `COMMAND_SCHEMA` | CLI schemas/command |
| `org.aurora.cli:configs/default` | `config` | `CONFIGURATION` | CLI configs/default |
| `org.aurora.cli:state/config` | `state_key` | `CONFIG` | CLI state/config |
| `org.aurora.cli:commands/about` | `command` | `CMD_ABOUT` | 了解 AuroraBot 与当前运行环境 |
| `org.aurora.cli:commands/check` | `command` | `CMD_CHECK` | 默认运行静态检查与快速边界测试；--full 运行完整测试，--coverage 统计完整覆盖率 |
| `org.aurora.cli:commands/ctx/get` | `command` | `CMD_CTX_GET` | 读取精确状态地址 |
| `org.aurora.cli:commands/ctx/set` | `command` | `CMD_CTX_SET` | 以 JSON 整项替换状态 |
| `org.aurora.cli:commands/ctx/delete` | `command` | `CMD_CTX_DELETE` | 删除精确状态地址 |
| `org.aurora.cli:commands/ctx/list` | `command` | `CMD_CTX_LIST` | 枚举已赋值地址 |
| `org.aurora.cli:commands/ctx/watch` | `command` | `CMD_CTX_WATCH` | 观察当前宿主后续变化，Ctrl+C 退出 |
| `org.aurora.cli:commands/donk/show` | `command` | `CMD_DONK_SHOW` | 显示 Python 工作区版本 |
| `org.aurora.cli:commands/donk/major` | `command` | `CMD_DONK_MAJOR` | 升级主版本号 |
| `org.aurora.cli:commands/donk/minor` | `command` | `CMD_DONK_MINOR` | 升级次版本号 |
| `org.aurora.cli:commands/donk/patch` | `command` | `CMD_DONK_PATCH` | 升级修订版本号 |
| `org.aurora.cli:commands/help` | `command` | `CMD_HELP` | 列出当前可用命令 |
| `org.aurora.cli:commands/id/list` | `command` | `CMD_ID_LIST` | 列出启动前已登记的公共 ID、类型和提供者，不启动装配 |
| `org.aurora.cli:commands/bot` | `command` | `CMD_BOT` | 快速启动完整 Bot 后端，读取项目 .env 与 data |
| `org.aurora.cli:commands/panel` | `command` | `CMD_PANEL` | 快速启动 Panel 开发服务器，连接已有后端 |
| `org.aurora.cli:commands/tui` | `command` | `CMD_TUI` | 快速启动 TUI，使用项目 .env 中的访问令牌 |
| `org.aurora.cli:commands/run` | `command` | `CMD_RUN` | 启动选定装配，Ctrl+C 停止 |
| `org.aurora.cli:commands/serve` | `command` | `CMD_SERVE` | 启动本机 API；keys 为开放状态 ID 数组（默认 CLI config），endpoints 为显式开放的产品端点 ID 数组 |

### aurora-config

[发行静态目录](../packages/aurora_config/plugin.meta.json)

#### aurora_config

[源清单](../packages/aurora_config/src/aurora_config/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.config:registries/configs` | `registry` | `CONFIGS` | 接收各插件提供的 ConfigSpec |
| `org.aurora.config:handlers/load` | `hook_handler` | `LOAD` | 加载全部声明配置并注入 ctx，准备配置编辑服务 |
| `org.aurora.config:endpoints/configuration` | `endpoint` | `CONFIGURATION` | 列出、读取和保存已声明的 TOML 配置 |

组件 `configuration`：持有当前宿主的配置加载与编辑服务

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.config:handlers/load` |
| 插槽 | — |
| 状态 | — |
| 借用资源 | — |
| 导出资源 | `configuration` |
| 资源映射 | — |

### aurora-control

[发行静态目录](../packages/aurora_control/plugin.meta.json)

#### aurora_control

[源清单](../packages/aurora_control/src/aurora_control/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.control:handlers/control` | `component` | `CONTROL` | 通用控制组件 |
| `org.aurora.control:handlers/control/execute` | `hook_handler` | `CONTROL_EXECUTE` | 通用控制执行插头 |
| `org.aurora.control:handlers/control/children` | `hook_slot` | `CONTROL_CHILDREN` | 通用控制子组件槽 |
| `org.aurora.control:handlers/control/serial` | `component` | `SERIAL` | 串行组件 |
| `org.aurora.control:handlers/control/serial/execute` | `hook_handler` | `SERIAL_EXECUTE` | 串行执行插头 |
| `org.aurora.control:handlers/control/serial/children` | `hook_slot` | `SERIAL_CHILDREN` | 串行子组件槽 |
| `org.aurora.control:handlers/control/branch` | `component` | `BRANCH` | 分支组件 |
| `org.aurora.control:handlers/control/branch/execute` | `hook_handler` | `BRANCH_EXECUTE` | 分支执行插头 |
| `org.aurora.control:handlers/control/branch/children` | `hook_slot` | `BRANCH_CHILDREN` | 分支子组件槽 |
| `org.aurora.control:handlers/control/while` | `component` | `WHILE` | 循环组件 |
| `org.aurora.control:handlers/control/while/execute` | `hook_handler` | `WHILE_EXECUTE` | 循环执行插头 |
| `org.aurora.control:handlers/control/while/children` | `hook_slot` | `WHILE_CHILDREN` | 循环子组件槽 |
| `org.aurora.control:handlers/control/parallel` | `component` | `PARALLEL` | 并行组件 |
| `org.aurora.control:handlers/control/parallel/execute` | `hook_handler` | `PARALLEL_EXECUTE` | 并行执行插头 |
| `org.aurora.control:handlers/control/parallel/children` | `hook_slot` | `PARALLEL_CHILDREN` | 并行子组件槽 |
| `org.aurora.control:state/control` | `state_key` | `CONTROL_STATE` | 在途执行状态 |

组件 `serial`：串行执行显式连接的子组件

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.control:handlers/control/serial/execute` |
| 插槽 | `org.aurora.control:handlers/control/serial/children` |
| 状态 | — |
| 借用资源 | — |
| 导出资源 | — |
| 资源映射 | — |

组件 `branch`：分支执行显式连接的子组件

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.control:handlers/control/branch/execute` |
| 插槽 | `org.aurora.control:handlers/control/branch/children` |
| 状态 | — |
| 借用资源 | `select` |
| 导出资源 | — |
| 资源映射 | — |

组件 `while`：循环执行显式连接的子组件

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.control:handlers/control/while/execute` |
| 插槽 | `org.aurora.control:handlers/control/while/children` |
| 状态 | — |
| 借用资源 | `condition` |
| 导出资源 | — |
| 资源映射 | — |
| 参数契约 | `while` |

组件 `parallel`：并行执行显式连接的子组件

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.control:handlers/control/parallel/execute` |
| 插槽 | `org.aurora.control:handlers/control/parallel/children` |
| 状态 | — |
| 借用资源 | — |
| 导出资源 | — |
| 资源映射 | — |
| 参数契约 | `parallel` |

### aurora-core

[发行静态目录](../packages/aurora_core/plugin.meta.json)

#### aurora_core（宿主）

[源清单](../packages/aurora_core/src/aurora_core/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.core:registries/registries` | `registry` | `REGISTRY_DIRECTORY` | 内核分类接收方：registries |
| `org.aurora.core:registries/plugins` | `registry` | `PLUGINS` | 内核分类接收方：plugins |
| `org.aurora.core:registries/operations` | `registry` | `OPERATIONS` | 内核分类接收方：operations |
| `org.aurora.core:registries/hook_slots` | `registry` | `HOOK_SLOTS` | 内核分类接收方：hook_slots |
| `org.aurora.core:registries/hook_handlers` | `registry` | `HOOK_HANDLERS` | 内核分类接收方：hook_handlers |
| `org.aurora.core:registries/resources` | `registry` | `RESOURCES` | 内核分类接收方：resources |
| `org.aurora.core:registries/services` | `registry` | `SERVICES` | 内核分类接收方：services |
| `org.aurora.core:registries/schemas` | `registry` | `SCHEMAS` | 内核分类接收方：schemas |
| `org.aurora.core:registries/state_keys` | `registry` | `STATE_KEYS` | 内核分类接收方：state_keys |
| `org.aurora.core:registries/events` | `registry` | `EVENTS` | 内核分类接收方：events |
| `org.aurora.core:lifecycle/config` | `hook_slot` | `CONFIG` | 宿主生命周期：config |
| `org.aurora.core:lifecycle/prepare` | `hook_slot` | `PREPARE` | 宿主生命周期：prepare |
| `org.aurora.core:lifecycle/start` | `hook_slot` | `START` | 宿主生命周期：start |
| `org.aurora.core:lifecycle/stop` | `hook_slot` | `STOP` | 宿主生命周期：stop |
| `org.aurora.core:lifecycle/clean` | `hook_slot` | `CLEAN` | 宿主生命周期：clean |
| `org.aurora.core:operations/ctx/get` | `operation` | `CTX_GET` | 共享状态操作：get |
| `org.aurora.core:operations/ctx/set` | `operation` | `CTX_SET` | 共享状态操作：set |
| `org.aurora.core:operations/ctx/delete` | `operation` | `CTX_DELETE` | 共享状态操作：delete |
| `org.aurora.core:operations/ctx/list` | `operation` | `CTX_LIST` | 共享状态操作：list |
| `org.aurora.core:operations/ctx/subscribe` | `operation` | `CTX_SUBSCRIBE` | 共享状态操作：subscribe |
| `org.aurora.core:operations/ctx/unsubscribe` | `operation` | `CTX_UNSUBSCRIBE` | 共享状态操作：unsubscribe |
| `org.aurora.core:events/ctx/changed` | `event` | `CTX_CHANGED` | 共享状态变化事件 |

### aurora-mcp

[发行静态目录](../packages/aurora_mcp/plugin.meta.json)

#### aurora_mcp

[源清单](../packages/aurora_mcp/src/aurora_mcp/plugins/clients/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.mcp:configs/default` | `config` | `CONFIGURATION` | MCP 连接和目录筛选配置 |
| `org.aurora.mcp:state/config` | `state_key` | `CONFIG_STATE` | 非持久的 MCP 配置 |
| `org.aurora.mcp:state/clients` | `state_key` | `CLIENT_STATUS` | MCP 连接观察状态 |
| `org.aurora.mcp:handlers/configure` | `hook_handler` | `CONFIGURE` | 选择配置的 MCP 连接 |
| `org.aurora.mcp:handlers/prepare` | `hook_handler` | `PREPARE` | 准备阶段端口 |
| `org.aurora.mcp:handlers/stop` | `hook_handler` | `STOP` | 停止接收并等待借用者结束 |
| `org.aurora.mcp:handlers/clean` | `hook_handler` | `CLEAN` | 关闭所有者创建的连接 |

组件 `clients`：

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.mcp:handlers/configure`、`org.aurora.mcp:handlers/prepare`、`org.aurora.mcp:handlers/stop`、`org.aurora.mcp:handlers/clean` |
| 插槽 | — |
| 状态 | — |
| 借用资源 | — |
| 导出资源 | `clients` |
| 资源映射 | — |

#### aurora_mcp.tools

[源清单](../packages/aurora_mcp/src/aurora_mcp/plugins/tools/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.mcp:components/tool` | `component` | `COMPONENT` | 单个 MCP 工具执行组件 |
| `org.aurora.mcp:components/tool/execute` | `hook_handler` | `EXECUTE` | 执行实例的一次调用 |
| `org.aurora.mcp:handlers/tools/prepare` | `hook_handler` | `PREPARE` | 准备阶段端口 |

动态定义规则：

- `TOOL_DEFINITIONS`：根 `org.aurora.mcp:tools`，kind `tool`。实际成员由运行目录提供。

组件 `catalog`：

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.mcp:handlers/tools/prepare` |
| 插槽 | — |
| 状态 | — |
| 借用资源 | `clients` |
| 导出资源 | `catalog` |
| 资源映射 | — |

#### aurora_mcp.world

[源清单](../packages/aurora_mcp/src/aurora_mcp/plugins/world/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.mcp:sources/resources` | `source` | `WORLD_SOURCE` | MCP 资源更新的世界来源工厂 |
| `org.aurora.mcp:state/world` | `state_key` | `WORLD_STATUS` | MCP 世界来源的非持久观察状态 |

组件 `source_resources`：

| 角色 | 声明 |
| --- | --- |
| 插头 | — |
| 插槽 | — |
| 状态 | — |
| 借用资源 | `clients` |
| 导出资源 | `resources` |
| 资源映射 | — |

### aurora-memory

[发行静态目录](../packages/aurora_memory/plugin.meta.json)

#### aurora_memory

[源清单](../packages/aurora_memory/src/aurora_memory/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.memory:configs/default` | `config` | `CONFIGURATION` | 记忆索引和分块配置声明 |
| `org.aurora.memory:state/config` | `state_key` | `CONFIG` | 非持久的索引与分块参数 |
| `org.aurora.memory:components/tool` | `component` | `COMPONENT` | 通过显式输入输出地址执行单一记忆动作 |
| `org.aurora.memory:components/store` | `component` | `STORE` | 按 owner 隔离的 SQLite 存储资源 |
| `org.aurora.memory:handlers/store/prepare` | `hook_handler` | `PREPARE` | 创建 SQLite 连接并绑定借用的 embedding |
| `org.aurora.memory:handlers/store/clean` | `hook_handler` | `CLEAN` | 关闭本实例的数据库连接，保留借用的模型资源 |
| `org.aurora.memory:components/tool/execute` | `hook_handler` | `EXECUTE` | 读取工具调用并将记忆操作结果写入输出状态 |
| `org.aurora.memory:tools/write` | `tool` | `WRITE` | 保存或更新长期文本记忆 |
| `org.aurora.memory:tools/search` | `tool` | `SEARCH` | 按语义检索当前 owner 的记忆 |
| `org.aurora.memory:tools/read` | `tool` | `READ` | 读取记忆全文及版本 |
| `org.aurora.memory:tools/delete` | `tool` | `DELETE` | 按预期版本删除记忆 |
| `org.aurora.memory:tools/reindex` | `tool` | `REINDEX` | 使用绑定的 embedding 重建当前 owner 的索引 |

组件 `store`：持有当前 owner 的数据库连接，向压缩桥导出记忆资源

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.memory:handlers/store/prepare`、`org.aurora.memory:handlers/store/clean` |
| 插槽 | — |
| 状态 | `config` |
| 借用资源 | `embedding` |
| 导出资源 | `memory` |
| 资源映射 | — |
| 参数契约 | `store` |

组件 `tool`：执行所选记忆动作，借用 embedding 并持有自己的数据库连接

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.memory:handlers/store/prepare`、`org.aurora.memory:handlers/store/clean`、`org.aurora.memory:components/tool/execute` |
| 插槽 | — |
| 状态 | `config`、`input`、`output` |
| 借用资源 | `embedding` |
| 导出资源 | — |
| 资源映射 | — |
| 参数契约 | `tool` |

#### aurora_memory.compaction

[源清单](../packages/aurora_memory/src/aurora_memory/compaction/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.memory:handlers/compaction/start` | `hook_handler` | `START` | 启动可恢复的摘要索引任务 |
| `org.aurora.memory:handlers/compaction/stop` | `hook_handler` | `STOP` | 停止并等待自有索引任务 |
| `org.aurora.memory:handlers/compaction/clean` | `hook_handler` | `CLEAN` | 确认后台任务已结束，不关闭借用的存储和模型 |

组件 `recorder`：压缩记录器及索引任务

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.memory:handlers/compaction/start`、`org.aurora.memory:handlers/compaction/stop`、`org.aurora.memory:handlers/compaction/clean` |
| 插槽 | — |
| 状态 | — |
| 借用资源 | `memory` |
| 导出资源 | `recorder` |
| 资源映射 | — |
| 参数契约 | `options` |

### aurora-model

[发行静态目录](../packages/aurora_model/plugin.meta.json)

#### aurora_model

[源清单](../packages/aurora_model/src/aurora_model/plugins/model/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.model:registries/adapters` | `registry` | `ADAPTERS` | 模型供应商工厂目录 |
| `org.aurora.model:services/embedding_client` | `service` | `EMBEDDING_CLIENT` | 文本向量协议 |
| `org.aurora.model:services/choice_client` | `service` | `CHOICE_CLIENT` | 有限选项决策协议 |
| `org.aurora.model:services/chat_client` | `service` | `CHAT_CLIENT` | 聊天客户端协议 |
| `org.aurora.model:schemas/chat/request` | `schema` | `CHAT_REQUEST` | 聊天请求数据契约 |
| `org.aurora.model:schemas/chat/response` | `schema` | `CHAT_RESPONSE` | 聊天响应数据契约 |
| `org.aurora.model:schemas/chat/chunk` | `schema` | `CHAT_CHUNK` | 聊天增量数据契约 |
| `org.aurora.model:schemas/chat/capabilities` | `schema` | `CHAT_CAPABILITIES` | 聊天客户端能力声明 |
| `org.aurora.model:handlers/chat/prepare` | `hook_handler` | `CHAT_PREPARE` | 创建并检查模型客户端 |
| `org.aurora.model:handlers/chat/clean` | `hook_handler` | `CHAT_CLEAN` | 关闭自有模型客户端 |
| `org.aurora.model:handlers/choice/prepare` | `hook_handler` | `CHOICE_PREPARE` | 创建并检查模型客户端 |
| `org.aurora.model:handlers/choice/clean` | `hook_handler` | `CHOICE_CLEAN` | 关闭自有模型客户端 |
| `org.aurora.model:handlers/embedding/prepare` | `hook_handler` | `EMBEDDING_PREPARE` | 创建并检查模型客户端 |
| `org.aurora.model:handlers/embedding/clean` | `hook_handler` | `EMBEDDING_CLEAN` | 关闭自有模型客户端 |

组件 `chat`：

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.model:handlers/chat/prepare`、`org.aurora.model:handlers/chat/clean` |
| 插槽 | — |
| 状态 | `profiles?` |
| 借用资源 | `catalog?` |
| 导出资源 | `model` |
| 资源映射 | — |
| 参数契约 | `resource` |

组件 `choice`：

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.model:handlers/choice/prepare`、`org.aurora.model:handlers/choice/clean` |
| 插槽 | — |
| 状态 | `profiles?` |
| 借用资源 | `catalog?` |
| 导出资源 | `model` |
| 资源映射 | — |
| 参数契约 | `resource` |

组件 `embedding`：

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.model:handlers/embedding/prepare`、`org.aurora.model:handlers/embedding/clean` |
| 插槽 | — |
| 状态 | `profiles?` |
| 借用资源 | `catalog?` |
| 导出资源 | `model` |
| 资源映射 | — |
| 参数契约 | `resource` |

#### aurora_model.configuration

[源清单](../packages/aurora_model/src/aurora_model/plugins/configuration/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.model:configs/profiles` | `config` | `PROFILES` | 模型 profile 配置声明 |
| `org.aurora.model:state/config` | `state_key` | `CONFIG` | 非持久的模型 profiles |
| `org.aurora.model:configs/bindings` | `config` | `ROLES` | 模型角色引用配置声明 |
| `org.aurora.model:state/bindings` | `state_key` | `BINDINGS` | 非持久的模型角色绑定 |

#### aurora_model.litellm

[源清单](../packages/aurora_model/src/aurora_model/plugins/litellm/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.model:adapters/litellm/chat` | `adapter` | `CHAT` | LiteLLM 聊天工厂 |
| `org.aurora.model:adapters/litellm/choice` | `adapter` | `CHOICE` | LiteLLM 决策工厂 |
| `org.aurora.model:adapters/litellm/embedding` | `adapter` | `EMBEDDING` | LiteLLM 向量工厂 |

### aurora-tools

[发行静态目录](../packages/aurora_tools/plugin.meta.json)

#### aurora_tools

[源清单](../packages/aurora_tools/src/aurora_tools/plugins/tools/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.tools:registries/tools` | `registry` | `TOOLS` | 可供应用选择的工具定义目录 |
| `org.aurora.tools:components/executor` | `component` | `EXECUTOR` | 顺序执行工具批次并保存结果的组件 |
| `org.aurora.tools:components/executor/execute` | `hook_handler` | `EXECUTE` | 执行实例的一次调用 |
| `org.aurora.tools:components/executor/children` | `hook_slot` | `CHILDREN` | 接收所选工具实例的执行槽 |
| `org.aurora.tools:executor/before_call` | `hook_slot` | `BEFORE_CALL` | 每次工具调用前的执行槽 |
| `org.aurora.tools:executor/after_call` | `hook_slot` | `AFTER_CALL` | 每次工具调用后的执行槽 |
| `org.aurora.tools:handlers/executor/configure` | `hook_handler` | `CONFIGURE` | 读取显式绑定的执行超时 |
| `org.aurora.tools:handlers/collection/prepare` | `hook_handler` | `COLLECT` | 创建工具成员并发布显式导出 |
| `org.aurora.tools:handlers/collection/clean` | `hook_handler` | `CLEAN` | 逆序关闭集合拥有的工具实例 |

组件 `executor`：

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.tools:components/executor/execute`、`org.aurora.tools:handlers/executor/configure` |
| 插槽 | `org.aurora.tools:components/executor/children`、`org.aurora.tools:executor/before_call`、`org.aurora.tools:executor/after_call` |
| 状态 | `input`、`output`、`current`、`config?` |
| 借用资源 | `recorder?` |
| 导出资源 | `executor` |
| 资源映射 | — |
| 参数契约 | `executor` |

组件 `collection`：

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.tools:handlers/collection/prepare`、`org.aurora.tools:handlers/collection/clean` |
| 插槽 | — |
| 状态 | `input`、`output` |
| 借用资源 | `catalog?` |
| 导出资源 | `catalog` |
| 资源映射 | `tools` |
| 参数契约 | `collection` |

#### aurora_tools.configuration

[源清单](../packages/aurora_tools/src/aurora_tools/plugins/configuration/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.tools:configs/executor` | `config` | `EXECUTOR` | executor 的行为参数 |
| `org.aurora.tools:state/executor/config` | `state_key` | `EXECUTOR_STATE` | executor 的非持久配置状态 |

### aurora-world

[发行静态目录](../packages/aurora_world/plugin.meta.json)

#### aurora_world.records

[源清单](../packages/aurora_world/src/aurora_world/plugins/records/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.world:state/records` | `state_key` | `RECORDS` | 世界事件的有界呈现状态 |
| `org.aurora.world:state/environment` | `state_key` | `ENVIRONMENT` | 时间和天气的有界环境观察 |
| `org.aurora.world:handlers/records/prepare` | `hook_handler` | `RECORDS_PREPARE` | 打开事件归档并恢复视图 |
| `org.aurora.world:handlers/records/start` | `hook_handler` | `RECORDS_START` | 启动有界视图的刷新任务 |
| `org.aurora.world:handlers/records/stop` | `hook_handler` | `RECORDS_STOP` | 停止自有刷新任务 |
| `org.aurora.world:handlers/records/clean` | `hook_handler` | `RECORDS_CLEAN` | 关闭事件数据库连接 |

组件 `records`：归档世界事件并维护有界 ctx 视图，不创建世界来源

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.world:handlers/records/prepare`、`org.aurora.world:handlers/records/start`、`org.aurora.world:handlers/records/stop`、`org.aurora.world:handlers/records/clean` |
| 插槽 | — |
| 状态 | — |
| 借用资源 | — |
| 导出资源 | `records` |
| 资源映射 | — |

#### aurora_world.sources

[源清单](../packages/aurora_world/src/aurora_world/plugins/sources/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.world:state/sources` | `state_key` | `SOURCE_STATUS` | 来源实例的非持久运行诊断 |
| `org.aurora.world:registries/sources` | `registry` | `SOURCES` | 世界来源工厂登记目录 |
| `org.aurora.world:handlers/sources/prepare` | `hook_handler` | `SOURCES_PREPARE` | 按选择创建来源并传入资源引用 |
| `org.aurora.world:handlers/sources/start` | `hook_handler` | `SOURCES_START` | 开放接纳入口并启动所选来源 |
| `org.aurora.world:handlers/sources/stop` | `hook_handler` | `SOURCES_STOP` | 停止接纳并结束所选来源任务 |
| `org.aurora.world:handlers/sources/clean` | `hook_handler` | `SOURCES_CLEAN` | 释放各来源持有的资源 |

组件 `sources`：选择来源工厂、管理任务与接纳入口，借用记录服务

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.world:handlers/sources/prepare`、`org.aurora.world:handlers/sources/start`、`org.aurora.world:handlers/sources/stop`、`org.aurora.world:handlers/sources/clean` |
| 插槽 | — |
| 状态 | — |
| 借用资源 | `records` |
| 导出资源 | `sources` |
| 资源映射 | — |

#### aurora_world.configuration

[源清单](../packages/aurora_world/src/aurora_world/plugins/configuration/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.world:state/config` | `state_key` | `CONFIG_STATE` | 非持久的来源与视图配置 |
| `org.aurora.world:configs/sources` | `config` | `CONFIGURATION` | 来源选择与视图参数声明 |
| `org.aurora.world:handlers/sources/configure` | `hook_handler` | `CONFIGURE` | 读取配置并向来源所有者提交明确的来源选择 |

组件 `configuration`：声明来源选择与视图参数，在 config 阶段配置已绑定的来源所有者

| 角色 | 声明 |
| --- | --- |
| 插头 | `org.aurora.world:handlers/sources/configure` |
| 插槽 | — |
| 状态 | — |
| 借用资源 | `sources` |
| 导出资源 | — |
| 资源映射 | `source_resources` |

#### aurora_world.environment

[源清单](../packages/aurora_world/src/aurora_world/plugins/environment/plugin.meta.toml)

| ID | kind | 符号 | 用途 |
| --- | --- | --- | --- |
| `org.aurora.world:sources/environment/time` | `source` | `TIME` | 周期时间观察来源 |
| `org.aurora.world:sources/environment/weather` | `source` | `WEATHER` | Open-Meteo 天气观察来源 |

## 维护与历史对账

清单与生成目录是权威数据，本页是可读索引。新增、移除或修改公开定义/组件角色时，先运行 `aurora-meta generate`，再核对本页；发布前运行 `aurora-meta generate --check`。内部算法变更不要求重写目录。

[原始能力盘点](plugin-capability-boundaries.md)保留迁移前 145 项定义。[验收对账](../tests/fixtures/metadata/baseline_ids.json)记录 135 项的新拥有者与清单，以及 10 项删除理由；它只用于测试，不提供运行时 ID 转换。当前目录的 225 项还包含 core/CLI 自举及新增定义，不能把两个统计直接当作插件能力的增减量。
