# AuroraBot 当前架构

核对日期：2026-11-10。文件名沿用现有引用，内容描述当前实现；旧 v0.2.3 设计保存在[历史归档](archive/2026-11-09/aurorabot-design-v0.2.3.md)。

Aurora 以 ID 登记、共享 ctx 和显式连接组织插件。后端负责装配与执行，TUI 和 Panel 通过共享客户端观察、提交输入和取消运行。面向个人单租户使用；命名空间和实例 ID 用于组织定义与数据，不构成租户隔离。

## 包边界

| 包 | 当前职责与依赖边界 |
| --- | --- |
| aurora_core | ID、登记、ctx、订阅、连接、调用、生命周期、持久化；不处理 TOML 或模型业务 |
| aurora_config | 基于 core 声明配置、校验结构与关联、补缺模板、加载 TOML；提供可选配置编辑端点 |
| aurora_control | 仅依赖 core；执行身份、状态绑定、插头插槽与 Serial、Branch、While、Parallel |
| aurora_agent | ReAct、模型调用、工具执行、默认阶段与 AgentRuntime；不依赖 bot、CLI、API |
| aurora_adapter | 基础包依赖 core；model 提供模型契约与供应商适配，mcp 提供协议与工具/世界桥；额外依赖通过 extra 安装 |
| aurora_bot | 默认配置、装配、资源、运行操作、直接交流、笔记、显式文本记忆、业务视图、cadence 与自身控制 |
| aurora_cli / aurora_api | 宿主、命令交互、HTTP/WS 传输；复用 bot 运行语义 |
| aurora_world | 来源管理、事件原文归档、近期视图、环境观察；含时间、天气及可选 MCP 世界接入 |
| aurora_logging | 日志配置 |
| aurora_client / apps | TS 共享客户端、OpenTUI、Vue Panel、静态站点；不装配 Python 插件 |

执行依赖方向为 `bot → agent → control → core`。agent 和 bot 可以直接使用 core 与 adapter.model；配置通过 aurora_config 接入。独立 aurora_harness 尚未实现，安装助手复用已有 MCP 产品装配。

## ID、ctx 与插件

ID 为 `<namespace>:<domain>/<local_path>`。公开定义按所属包命名；定义身份、实例身份、run_id 和 execution_id 分开。ctx 地址由状态 ID 与精确 location 共同确定，JSON null 与地址不存在不同。

ctx 值使用可序列化 JSON，运行期客户端和连接不进入快照。配置状态 persistent=False，持久来源为 TOML；业务状态由宿主保留或裁剪，core 不推断业务完成。

插件发现分组为 aurora.plugins，entry point 名称与 Plugin.name 一致。安装包与启用插件分开，requires 只校验已显式启用的依赖。插件发现、ID 查询和模板生成不创建模型、工具或后台任务。缺少可选接收方可以保留未连接声明；执行连接由接收方核对契约。

实际定义见[公共 ID 目录](aurorabot-id-catalog-v0.2.3.md)，安装独立性见[执行包边界](aurora_agent_extraction_assessment.md)。

## 启动与关闭

宿主建立登记、ctx、连接和存储，恢复业务快照，依次执行 `config → prepare → start`。config 完成全部配置校验与注入；prepare 创建模型、MCP 连接和工具；start 接收工作。配置文件只补缺失项，不覆盖已有文件。

关闭按组件依赖逆序进行：停止接收新工作，取消并等待自有运行，关闭工具、模型与 MCP，再完成最终持久化与 ctx 清理。中断的工具动作不自动重试；恢复快照不等于透明续跑。旧公共 ID 的状态不得被静默丢弃以绕过恢复错误。

实现入口：[Lifecycle](../packages/aurora_core/src/aurora_core/lifecycle.py)、[CLI 宿主](../packages/aurora_cli/src/aurora_cli/host.py)、[默认装配](../packages/aurora_bot/src/aurora_bot/assembly.py)。

## 执行与输入

每个 agent 实例只有一个 AgentRuntime 所有者。用户直接交流、cadence 和计划唤醒都向这个所有者提交引导；运行中的输入在推理边界接纳。等待者取消不隐式取消 agent，显式取消会等待清理。调用等待决定执行结束，不能用残留状态判断完成。

ReAct 提供 prepare、infer、act、observe、finish、error 阶段连接。默认阶段构造模型输入、调用模型、执行工具，把完整请求与返回一起写回历史。模型无工具调用且正常 stop 时结束；工具错误作为观察返回，不自动重试副作用。

模型消息支持文本和结构化内容，思考文本及供应商需要的思考块保留在工具往返中。输入预算以应用层 JSON 字符和内嵌文件字节计，不是 token 上限。详见[上下文与运行](context.md)。

记忆插件 `aurora_bot.memory` 通过现有工具工厂接入，Bot 所有者负责关闭它的数据库与向量客户端。向量协议及 LiteLLM 传输归 `aurora_adapter.model`，模型 profile 通过统一模型注册表按 embedding 用途解析。原文和可重建索引保存在插件 SQLite，不增加 agent 调度所有者、不将记忆策略下沉到 core。使用与持久化约束见[文本记忆配置](configuration.md#显式文本记忆朴素-rag)。

## 模型边界

`aurora_adapter.model` 按职责平铺：`contract.py` 提供 SDK 无关的数据与 ChatClient、ChoiceClient、EmbeddingClient、泛型 ModelFactory；`config.py` 解析配置与用途；`content.py` 校验输入及预算；`response.py` 收集响应与校验向量；`litellm.py` 持有供应商客户端，`_codec.py` 转换 Aurora 消息；`testing.py` 提供确定性假模型，`plugin.py` 登记定义并延迟导入 SDK。

三类客户端共用 LiteLLMClient 的实例传输、并发约束、错误脱敏与关闭逻辑；聊天调用 `acompletion`，向量调用 `aembedding`。流中的文本即时交付，工具及思考碎片使用 LiteLLM 的 ChunkProcessor 合并，再校验完整身份、参数及签名；不调用完整 stream_chunk_builder 重算 token 或重复缓存正文。SDK 类型不进入 ctx 或上层协议。

LiteLLM 固定在 `>=1.106.6,<1.107`。当前高层 decisions 接口不透传实例 client，choice 使用 SDK 的 prepare_call、供应商转换及底层 handler 注入连接。OpenAI embedding 分支会覆盖零重试设置，因此自有 OpenAI 客户端固定零重试；DeepSeek 聊天沿用 OpenAI 兼容路由保留文件及思考字段。这些是升级 SDK 时须复验的薄适配边界，未引入共享 Router。

自定义插件迁移：旧 `models/protocols/decisions/embeddings` 的协议统一从包公共出口或 `contract` 导入，响应收集和向量校验从 `response` 导入，`configuration` 改为 `config`，`fake` 改为 `testing`；`ModelClient/Request/Response/Chunk/Capabilities` 分别改为对应的 `Chat*`。三个 resolver 合并为 `resolve_model(..., kind="chat"|"choice"|"embedding")`，返回 `ResolvedModel[T]`；工厂使用 `ModelAdapter(kind, factory)` 登记到 `registries/model/adapters`，不再使用 choice_adapters 或 embedding_adapters。

公共 ID 的命名空间仍为 `org.aurora.adapter`：`services/model/client` 改为 `services/model/chat_client`；四个 `schemas/model/{request,response,chunk,capabilities}` 改为 `schemas/model/chat/{request,response,chunk,capabilities}`。choice/embedding 服务、插件名、配置及业务状态 ID 保持原值。旧模块、旧工厂类型和旧 ID 无兼容转发；TOML 与索引迁移见[升级说明](configuration.md#从旧模型配置升级)。

## MCP 与世界输入

MCP 使用 schema_version=2 的 servers 配置；支持 remote HTTP 和 local stdio。客户端统一持有连接，工具桥和世界桥借用同一连接。工具目录只进入已启用的工具桥；世界资源必须在 world 配置中显式选择。

世界事件原文保存在 SQLite，ctx 暴露有界近期视图；环境观察按来源保留。cadence 可原样转交世界输入，也可通过 choice 模型选择 observe、attend_events 或 review_work。计划唤醒与暂停由 bot 自身控制工具提供。这些能力已实现，但不会在安装助手中默认启用。

## API 与界面

API 显式开放 ctx ID、只读 ID 和产品端点；默认只允许回环非浏览器访问。浏览器来源、代理主机和令牌由 AccessPolicy 控制。HTTP/WS 不是任意插件操作的通用远端执行入口。

直接交流使用 session_id、instance_id、request_id 区分提交；accepted 只表示接纳，run_status 表示关联运行进度。重连不自动补发动作；宿主重启后旧会话身份失效。配置编辑仅处理已声明 TOML，校验与修订检查通过后保存，重启生效。ctx 写入不保存 TOML、不重建资源。

TUI 支持交流、状态、ctx 与声明 TOML 编辑及本地偏好；Panel 提供交流、附件和只读状态。附件和模型历史会进入持久上下文。具体操作见[操作指南](operations.md)。

## 用户入口与实现状态

唯一用户示例是[安装配置助手](../examples/START.md)，通过 terminal MCP 帮助首次配置。正式产品使用 scripts/bot.py，快捷命令为 aurora bot；Panel、TUI 分别由对应 scripts 启动。

旧五组离线应用仅作为[回归夹具](../tests/fixtures/runtime_apps/)保留，覆盖跨包、恢复、取消和常驻宿主行为，不属于用户启动路径。历史里程碑和讨论见[归档索引](INDEX.md#历史资料)，未完成清单不自动成为当前承诺。变更与实际验收统一记录到 [CHAGELOG.md](CHAGELOG.md)。
