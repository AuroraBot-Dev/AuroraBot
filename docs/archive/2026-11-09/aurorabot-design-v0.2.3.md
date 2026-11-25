# AuroraBot 初期设计文档 v0.2.3

> 历史归档：2026-11-09。保留当时的设计、计划与验收语境，不作为当前功能承诺或操作指南；当前入口见 [文档索引](../../INDEX.md)。

版本：v0.2.3
设计版本日期：2026-10-29；执行包拆分、M2 验收与文档基线对齐：2026-11-01。

状态：架构基线与当前实现说明；M2 已完成，M3 已交付本机 ctx 传输、按需契约、共享客户端、M3.6 直接交流及 OpenTUI 交流/状态页、ctx 编辑、声明 TOML 编辑与本地偏好。M3.9 完整联调和 M4-W 尚待交付。规划部分不代表已交付。

配套附件：[公共 ID 目录](aurorabot-id-catalog-v0.2.3.md)。保留规划身份并列出当前组件定义；名称存在不表示行为或字段已经冻结。

执行能力由三个平级包分担：`aurora_control` 提供执行契约与四种控制组合，`aurora_agent` 提供 ReAct、模型调用、工具执行与运行调度，`aurora_bot` 负责默认装配、资源和产品入口。五条可运行示例见 [启动指南](START.md)，执行定义见 [公共 ID 目录第 6 节](aurorabot-id-catalog-v0.2.3.md#6-控制agentbot-与世界定义)，独立 harness 的边界与后续工作见 [拆包评估](aurora_agent_extraction_assessment.md)。本文其余规划部分保留设计语境，当前验收范围见 [变更记录](../../CHAGELOG.md)。

## 1. 项目概述

AuroraBot 是一个以 ctx/hook 为总线、以 entrypoint 为插件发现入口、以命名空间 ID 为统一寻址方式的 bot 框架。Python 侧提供运行环境与能力装配，TypeScript 侧提供共享客户端、TUI、WebUI、文档站与落地页。

总体架构采用微内核与插件装配：`aurora_core` 提供共享 ctx、对象登记与寻址、连接及最小调用机制；`aurora_control` 提供执行契约和控制组合；`aurora_agent` 提供 ReAct、模型调用、工具执行与运行调度；`aurora_bot` 装配默认产品；模型适配层提供统一模型服务；CLI 提供命令交互，API 为客户端连接后端提供传输支持。

公开资源、操作、插槽和扩展项使用稳定 ID 相互引用。命名空间组织归属与名称，组件通过显式连接组合；接口和 schema 随实际协作需要逐步明确，不要求先建立完整契约体系才能运行。

### 1.1 服务场景

AuroraBot 面向个人单租户场景。一个唯一的 bot 后端提供共享运行环境，TUI、Panel 通过 client 与该后端的 ctx 交互。系统不引入多租户运行隔离或多租户记忆隔离。

会话、运行和 agent 标识用于组织业务数据与执行状态，不表示租户或插件访问权限边界。界面的本地视图状态不必全部进入后端 ctx。

插件通常在后端进程内通过 ctx、服务和插头／插槽介入系统。TUI、Panel 是交互界面，不承担插件发现、装配或执行树扩展职责。HTTP/WS 是客户端与后端之间的传输实现。

## 2. 设计原则

1. **core 只做通用机制。** 提供 ID 登记与寻址、共享 ctx、订阅、连接、生命周期及最小调用机制；具体业务和流程控制由插件实现。
2. **bot 装配能力，不另造机制。** bot 包可以包含默认插件实现，但装配职责保持薄，不将业务机制下沉到 core。
3. **公开对象统一寻址。** 跨组件引用使用稳定 ID；参与 bot 执行连接的组件及其端口显式登记，不要求每个私有辅助函数或运行时对象都有公共 ID。
4. **接口按需明确。** 双方通常描述各自接口，由接收方判断兼容性；少量特殊连接可以依赖双方约定和运行时行为，不强制独立 schema 或公共 schema ID。
5. **连接由提供插槽的一方判断。** 接口不完全相同不等于不能连接；core 不以 schema 相等作为全局接入条件。
6. **缺少接收方时允许未连接。** 未安装或未启用 CLI/API 等宿主时，保留相关声明并告警，不因可选入口缺席而阻断其他能力运行。
7. **统一 ctx 访问语义。** 插件通过进程内接口访问 ctx；TUI、Panel 通过 client 的对应接口访问同一个 ctx，实际状态操作由 core 完成。
8. **模型适配透明。** bot 使用统一 ModelClient，不直接依赖 LiteLLM 或具体模型 SDK。
9. **共享状态与显式变更。** ctx 以内存为工作区；所有状态修改经过显式接口，需要恢复的数据异步落盘，正常退出前完成最后写入。
10. **身份与实例分离。** 公共 ID 标识定义，实例标识定位具体对象；命名空间不构成内部 ctx 访问隔离边界。
11. **按连接与依赖逐步关闭。** 停止新工作，让工作组件收尾并逐步断开，ctx 与存储留到最后完成落盘。

## 3. 包与职责

### 3.1 Python 侧

| 包 | 职责 | 边界 |
| --- | --- | --- |
| `aurora_core` | 内存 ID 登记表、共享 ctx 与持久化基础、事件订阅、插槽连接、最小调用及生命周期 | 不实现 bot、模型、工具或具体流程控制业务；不承担 TOML 加载与配置 schema 策略 |
| `aurora_config` | 配置声明、结构及关联校验、TOML 模板处理与 config 阶段服务 | 基于 core；不承担模型、agent 或业务流程 |
| `aurora_cli` | 启动前 ctx 预配置、命令发现、argv 解析、命令交互 | 不重复实现 ctx 或 bot 业务语义；缺席不影响无 CLI 的装配 |
| `aurora_control` | 执行身份、状态绑定、连接契约与四种控制组合 | 仅依赖 core，不依赖 agent 或模型 |
| `aurora_agent` | ReAct、模型调用、工具执行、默认阶段与运行调度 | 不依赖 bot、CLI 或 API；资源与地址由宿主提供 |
| `aurora_bot` | 默认配置与 TOML 模板、产品装配、资源所有权、运行操作及命令 | 不硬依赖 CLI/API 实现，不直接依赖具体模型 SDK；不复制 agent 的执行机制 |
| `aurora_api` | client 与后端 ctx 交互所需的 HTTP/WS 传输、端点、事件信封及实际需要的契约导出 | 不作为插件接入总线，不预设任意 operation 的远端分发器 |
| `aurora_logging` | 宿主与库共用的日志级别、控制台输出、回溯与文件落盘配置 | 不依赖业务包，不参与 ctx 或插件登记 |
| `aurora_world` | 世界记录、来源去重、位置读取及进程内来源装配已交付；TOML/内置来源按 M4-W 扩展 | 基于 core，配置复用 config；不依赖 bot/agent，不负责唤醒或选择目标 |
| `aurora_adapter` | model 提供 ModelClient、能力声明、模型配置与 LiteLLM；mcp 提供外部连接、世界和工具桥 | 基础包仅依赖 core；SDK 与桥按 extra 安装，插件分别显式启用 |

代码依赖方向为 `core ← config` 与 `core ← control ← agent ← bot`；`adapter` 基础包仅依赖 core，模型配置通过 model extra 引入 config，供应商 SDK 通过 litellm extra 安装；模型协议被 agent 与 bot 使用。`aurora_harness` 是后续独立项目，目标集合为 core、config、adapter.model、control 与 agent；bot 的配置、默认装配、运行操作和命令不进入 harness 的必需依赖。当前拆包边界与验收记录见 [拆包评估](aurora_agent_extraction_assessment.md)。

### 3.2 TypeScript 侧与静态应用

| 包或应用 | 职责 | 边界 |
| --- | --- | --- |
| `aurora_client` | ctx 访问接口及对应 ID 入口、连接、传输、订阅和所需生成类型 | 复用 core 的 ctx 语义；不重建后端插件系统 |
| `aurora_tui` | 使用 OpenTUI 构建终端对话、配置、ctx 查看与操作 | 通过 client 交互，保留终端界面行为 |
| `aurora_panel` | 使用 Vue 生态构建 Web 对话、配置、ctx 查看与操作 | 通过 client 交互，保留 Web 界面行为 |
| `docsite` | 文档页面、导航与公共 ID 参考 | 独立静态构建，不参与后端装配 |
| `landing` | 项目介绍、导航与品牌资源 | 独立静态构建，不参与后端装配 |

以下 TS 包与静态应用尚未全部建立，保留为设计边界；当前仓库已有 `aurora_client` 骨架以及 `apps/aurora_tui`、`apps/aurora_panel`、`apps/docsite`、`apps/landing` 的入口，业务实现随 M3、M4 推进。

“bot 包保持薄”约束装配职责。默认能力可以作为插件与装配代码同包发布，或以后拆分；命名空间归属不要求与物理代码目录一一对应。

## 4. 命名空间与统一 ID

### 4.1 格式与解释

```text
<namespace>:<domain>/<local_path>
```

`namespace` 标识公开定义归属，`domain` 组织功能，`local_path` 定位对象，可包含多级 `/`。

| 示例 ID | 含义 |
| --- | --- |
| `org.aurora.cli:commands/help` | help 命令入口 |
| `org.aurora.bot:prompts/soul` | soul 提示词资源 |
| `org.aurora.agent:react/prepare` | ReAct prepare 插槽 |

命名空间使用点分隔；域和路径段使用小写 `snake_case`，段内允许数字。不得包含空段、空格、前后斜杠、`.` 或 `..` 路径段。跨组件引用使用完整 ID；交互短名只能在明确上下文中解析，歧义时报错。

ID 不自动映射为文件路径、导入路径、HTTP URL、执行顺序或组件父子关系。`kind` 由登记信息声明，不从路径前缀推断。

### 4.2 命名空间与解析环境

| 包或应用 | 命名空间 | 定义所在环境 |
| --- | --- | --- |
| `aurora_core` | `org.aurora.core` | Python 运行时 |
| `aurora_config` | `org.aurora.config` | Python 运行时 |
| `aurora_cli` | `org.aurora.cli` | Python 运行时 |
| `aurora_control` | `org.aurora.control` | Python 运行时 |
| `aurora_agent` | `org.aurora.agent` | Python 运行时 |
| `aurora_bot` | `org.aurora.bot` | Python 运行时 |
| `aurora_api` | `org.aurora.api` | Python 运行时 |
| `aurora_logging` | `org.aurora.logging` | Python 运行时；当前未登记公共定义 |
| `aurora_world` | `org.aurora.world` | Python 运行时；已登记世界记录、来源注册表及生命周期处理器 |
| `aurora_adapter` | `org.aurora.adapter` | Python 运行时；模型协议、配置、工厂及可选 MCP 插件 |
| `aurora_client` | `org.aurora.client` | TS 客户端 |
| `aurora_tui` | `org.aurora.tui` | TUI 本地 |
| `aurora_panel` | `org.aurora.panel` | WebUI 本地 |
| `docsite` | `org.aurora.docsite` | 文档构建环境 |
| `landing` | `org.aurora.landing` | 落地页构建环境 |

第三方使用自己的命名空间。`org.aurora.*` 由官方维护；名称表达归属，不构成身份认证或 ctx 访问授权。代码移动不要求 ID 随之变化。

定义所在环境和引用所在环境可以不同。client 可以实现携带既有 ctx 操作 ID 的访问入口，不需要将后端 Python 对象装入 TS 注册表。静态资源和本地视图也不会自动进入 Python 的 ID 表。

### 4.3 对象类型

| kind | 语义 |
| --- | --- |
| `registry` | 接收一类或多类登记项，提供对应接入规则 |
| `operation` | 可调用能力，输入输出按实际需要描述 |
| `component` | 组件定义，指向类或局部执行函数；实例及其端口连接另行创建 |
| `hook_slot` | 组件提供的接入位置，负责判断接入兼容性 |
| `hook_handler` | 可接入插槽的处理实现，即插头 |
| `resource` | 可加载的数据或内容 |
| `service` | 可绑定、注入和管理的服务定义 |
| `schema` | 需要显式维护的数据描述与校验定义 |
| `state_key` | ctx 状态项定义，不建立内部访问隔离 |
| `event` | 可发布、订阅的事件类型定义 |
| `config` | 配置声明，关联非持久状态、结构校验与 TOML 模板 |
| `command`、`adapter`、`assembly`、`endpoint` | 由对应接收方解释的扩展类型 |
| 视图、界面动作、页面、生成契约 | 由本地应用或构建环境解释的类型 |

可寻址不意味着可执行。登记项可以指向函数、插槽对象、资源、服务描述、工厂等，不统一转换为 callable。对象可以附带 schema，也可以通过语言类型、函数签名或双方约定描述接口。

### 4.4 定义与实例

公共 ID 标识定义；同一定义创建的多个对象通过实例标识区分，不以业务数据改变定义身份。执行组件当前使用以下身份：

| 字段 | 用途 |
| --- | --- |
| `definition_id` | 完整 `Id`，组件定义登记为 `component` |
| `instance_id` | 实例身份，默认 UUID，可显式指定非空字符串；同一组件反复取得 plug 保持身份 |
| `run_id` | 一次业务运行，父子调用共享 |
| `execution_id` | 单次调用，每次子调用生成新身份并记录 parent_execution_id |
| `reference` | `definition_id.instance_id` 展示引用；不作为新的 `Id` 解析 |

bot 的 `component_entries` 显式声明组件及其 `/execute` 插头，有子组件时声明 `/children` 插槽。这是插件的命名约定，core 不从路径推断 kind 或运行时父子关系。同一插槽的子 instance_id 唯一；生命周期宿主内的 LifecycleComponent instance_id 也须唯一。

ctx 地址由状态项 ID 和显式业务定位组成。`StateBinding` 在给定 location 上加入 run_id，不自动加入定义或实例身份；需要实例隔离的组件必须在地址约定中表达。控制状态额外使用定义、实例、运行和调用四个字段。地址不建立多租户隔离或并发写保护。

### 4.5 唯一性、覆盖与版本

同一环境、同一登记作用域内，一个完整 ID 对应一个公开定义，不通过改变 kind 复用同一 ID。覆盖、实现选择和替换通过显式装配表达，避免依赖加载顺序。

多个不同 ID 的处理器接入同一插槽是正常扩展；同一定义的多个实例使用实例标识区分。

需要稳定维护的公共接口记录契约版本，包版本与契约版本分别管理。兼容判断由接收方结合接口和实际实现完成，不要求所有局部连接先建立独立版本契约。重命名与不兼容变更显式说明，不做静默猜测。

## 5. ctx、共享状态与存储

### 5.1 运行时数据中心

ctx 是 bot 运行时数据的集散中心，以内存为工作区。所有命名空间均通过显式接口读取和修改共享状态，不按命名空间分配读写权限。

命名空间组织定义、数据归属与目录；跨命名空间修改遵守同样的状态接口和变化通知规则。

### 5.2 统一访问接口

core 提供读取、写入、删除、枚举、订阅和取消订阅等轻量原语。Python 插件使用进程内接口，CLI 使用对应入口，TUI/Panel 使用 client 提供的对应接口。各语言实现共享访问语义，不要求 Python 插件依赖 TS 包。

client 实现 ctx 操作相关的访问入口与 ID 支持，沿用已有 `org.aurora.core:operations/ctx/...` 身份，不为同一动作创建一套同义 ID。后端实际操作、状态变更和通知仍由 core 完成。

所有状态修改经过显式接口，执行实际配置的校验、变化通知及持久化安排。当前读写使用深复制，set 整项替换；外部原地修改读出值或写入参数不能改变内部状态。

list 返回已赋值的精确地址并排序；缺失 get 抛 KeyError，已登记状态项的缺失地址 delete 返回 False。每次成功 set 都通知，即使值相同；失败写入无部分变更。订阅接收后续变化，不回放历史。ctx 限宿主线程访问，同线程单次修改有序，读改写组合不是事务。不为每种局部请求强制创建独立 schema。

### 5.3 自动持久化与运行时对象

需要恢复的数据在运行期间异步自动落盘。正常退出前完成待写入数据及停止过程中最后变更的落盘，再释放相关内存。

当前持久化保存 persistent 状态，并要求严格 JSON 数据；Context.set 本身只执行已配置的状态校验，不保证值一定能落盘。运行时服务对象、连接、函数与任务由装配持有，不进入 ctx。凭证通过运行期参数注入。模型配置与角色绑定使用 `aurora_config` 的非持久配置状态与 `org.aurora.adapter:state/model/config`、`state/model/bindings`，启动时重建客户端；不建立独立的运行时对象管理器或完整状态分类系统。

ContextPersistence 默认每 0.5 秒合并写入，临时文件写完后替换正式快照；宿主先恢复，再执行 config 阶段，之后 configure 与 prepare/start。异步写入不承诺崩溃零丢失，正常退出由宿主保证最终 flush。业务保留策略由应用决定；controller 清理终态调用，示例清理中间值及历史结果，core 不裁剪完整快照。

配置由 `aurora_config` 声明与加载：插件通过 `ConfigSpec`、`ConfigSchema`、`ConfigTemplate` 与 `config_entries` 声明配置及对应的非持久状态。宿主在恢复业务状态后执行 config 阶段，完成全部文件与关联校验并原子注入 ctx，再执行 prepare/start。TOML 是配置的持久来源，只复制缺失的用户文件，不覆盖已有内容；运行期凭证单独解析，不进入模板、ctx、快照或日志。

### 5.4 命名空间目录与结构化存储

core 的 StorageService 接收宿主显式传入的数据根，提供 `framework/ctx.json` 快照、`framework/structured.sqlite3` JSON KV 存储及插件命名空间目录。存储对象由装配持有，不新增独立公共 ID。

插件可以在分配目录中自主维护数据库，负责模型、索引、事务、连接和迁移。框架不接管数据库内部结构，也不要求数据库内容全部保存为 ctx 内存镜像。

### 5.5 内部共享与客户端数据

内部 ctx 跨命名空间共享。manifest 可以声明数据与能力依赖，但不构成内部访问许可流程。初期不提供同进程恶意插件隔离。

client 获取准备提供给界面的数据，不将整个 Python ctx 无差别序列化。敏感配置和连接凭证不因通用 ctx 接口自动暴露；订阅与错误信息同样遵循实际的数据提供规则。对外访问控制不改变内部共享模型。

本版只确定上述边界，不提前选定完整状态标签、凭证管理或授权系统。监听与认证方式、需要提供的数据范围在实现外部连接时具体确定。

## 6. ID 登记与插件发现

### 6.1 统一内存登记表

core 在当前 Python 运行环境的登记作用域内维护统一哈希表：

```python
definitions: dict[Id, RegistryEntry]
```

`RegistryEntry` 称为“登记项”，描述一个 ID 对应的公开定义，并指向实际对象或加载入口。它与 ctx 中的状态值、某次事件、具体运行实例分开管理。

| 信息 | 用途 |
| --- | --- |
| `id`、`kind` | 定位定义并说明类型 |
| 对象引用或加载入口 | 指向处理器、插槽、资源、服务描述、工厂等实际内容 |
| 提供者信息 | 说明来源及归属 |
| `register_to`、`slot` 等关系 | 按对象需要记录接收方与连接目标 |
| 可选接口描述 | 输入输出、schema 引用、语言类型或其他必要描述 |

上表是概念结构，不冻结字段序列化格式，也不为登记项新增公共 ID。总表中的存在不意味着目标接收方已经存在、连接已经建立或对象正在运行。

commands、hook_slots、resources 等逻辑注册表可以基于总表提供分类索引或视图，并执行各自接入逻辑，不要求各自重复维护完整对象存储。

### 6.2 注册表自举与登记关系

宿主直接创建统一登记表、注册表目录及所需基础定义，随后登记其他对象。自举不要求先通过尚未建立的目录发现自身。

| 注册表 | 登记关系 |
| --- | --- |
| `org.aurora.core:registries/registries` | 由宿主直接引导建立；自身描述是否在目录中列出属于实现选择 |
| core 其余逻辑注册表 | 登记到上述注册表目录 |
| CLI commands、模型 adapters、agent tools、bot agents、API endpoints、config 配置声明；外部 adapter 定义待实现 | 对应提供方存在时登记到上述目录 |
| TS 本地与静态构建目录 | 在各自环境管理，不自动登记到 Python core |

通用 resources 注册表可以接收 resource、assembly、contract 等已约定类型。登记项保留自己的 kind，由接收方按需要选择加载与校验方式；不因进入 resources 就改成另一种身份。prompt、theme、keymap 等具体内容可附带必要描述，不强制建立完整子类型系统。

### 6.3 声明与可选宿主

声明可以包含 `id`、`kind`、`register_to`、`slot`、`operation`、可选 schema、依赖和排序信息。单个 `operation` 表达一个调用目标；一个端点绑定多个操作时，由端点自身描述各条传输绑定，不要求所有类型共享一个复杂通用字段结构。

```yaml
id: dev.example.memory:handlers/inject_context
kind: hook_handler
register_to: org.aurora.core:registries/hook_handlers
slot: org.aurora.agent:react/prepare
```

此示例只表达关系，ReAct 目标插槽仍为规划入口；不要求特殊连接补齐所有元数据。正式公共接口可以声明双方的输入输出；具体兼容性由插槽提供方判断。

未安装或未启用 CLI/API 时，指向其注册表的声明保留为未连接并输出 warning，不因这些入口缺席而拒绝加载整个插件。插件提供的其他能力仍可使用；未连接声明不会自行产生调用。接收方后来是否可动态启用属于热插拔议题，本版不作要求。

“未连接”不同于已成功建立连接。实际需要调用的目标若缺失，由调用入口或控制组件报告无法执行；不把未连接入口当成可用入口。

### 6.4 发现与装配

1. 宿主建立 core 总表、目录、ctx 及必要基础能力。
2. 读取显式装配清单，并按配置发现 `aurora.plugins` 入口点。
3. 收集定义和连接声明，登记 ID，检查重复身份等基础问题。
4. 已存在的接收方处理登记与连接，按需要判断接口兼容性；缺席的接收方记录 warning 与未连接状态。
5. 选择组件实例、资源与服务，形成当前装配。
6. 执行 config 阶段校验并注入配置，再执行生命周期 prepare/start，工作结束后按依赖逐步停止。

entry point 的 group、名称和导入路径只承担发现职责。实现只检查实际需要的规则，不以“缺少独立契约文件”为理由拒绝可以运行的特殊连接。

## 7. hook、插头与插槽

### 7.1 连接模型

`hook_handler` 表达可接入的处理能力，即插头；`hook_slot` 表达组件预留的接入位置，即插槽；`assembly` 表达组件选择、实例连接及资源和服务绑定。

组件可以同时提供插头与插槽。公共处理器与公共插槽分别拥有 ID，通过显式关系连接；运行时实例连接还应能区分各组件实例，不从 ID 路径或同名关系推导。

control 的 ExecutionPlug/ExecutionSlot 在连接时交换双方 StateBinding 与可选 schema。业务输入输出由实例自行读写 ctx；执行请求仅携带 run_id、execution_id 与父调用身份，返回值不承载业务结果。调用方等待执行来判断结束，订阅 ctx 变化或事件来观察更新；组件可按实际需要订阅变化触发工作，但不默认所有写入都是执行入口。core 的通用调用接口仍可处理普通函数参数与返回值。

### 7.2 接口描述与兼容判断

提供插头和插槽的双方通常各自描述输入输出，已有 schema 时可引用。插槽提供方决定自己能接收什么、是否适配以及怎样执行，core 提供登记、连接和最小调用支持。

| 情况 | 处理方向 |
| --- | --- |
| 双方描述一致 | 接收方按自身规则连接 |
| 描述不同但可兼容 | 允许连接；ExecutionSlot 在双方均提供 schema 且描述不同时输出 warning |
| 无法静态确认兼容 | 接收方可允许尝试并告警，由运行时检验实际行为 |
| 少量特殊连接没有正式 schema | 可以依赖签名、类型、双方约定和实际运行，不强制补契约 |
| 接收方明确无法处理 | 可以拒绝该连接，并说明原因，不将其伪装为成功连接 |

兼容性不等于 schema 文本相等，也不要求 core 建立通用兼容证明系统。双方确实需要适配时，由实际组件完成，不承诺框架自动转换任意数据。

`org.aurora.core:schemas/hook_slot` 保留为可使用的描述入口，不是每个连接必须提供的独立 schema。可复用、第三方实现或跨语言边界出现实际需要时，再提炼并稳定相应描述。

### 7.3 树形装配与控制组件

整体采用类似插排的树形组件组合，从根入口进入，由组件调用连接的子组件。顺序、并行、选择、循环由相应插件实现；core 不实现 ReAct 或通用流程控制业务。

前序遍历可以帮助理解普通顺序组合，不能统一决定所有控制组件的行为。控制组件自行决定子调用、ctx 更新和终止，公共 ID、发现顺序、表格行序均不决定执行顺序。调用结构、共享服务和生命周期依赖分别表达，不要求所有关系构成严格树。

当前 `aurora_control` 插件提供 Controller 基类与四类控制组件：

| 组件 | 行为 |
| --- | --- |
| Serial | 按连接优先级逐个等待，失败或取消停止后续调用 |
| Branch | 选择一个子 instance_id；None 跳过，未知实例报错 |
| While | 前置条件、唯一循环体、显式正整数 max_iterations；达到上限且条件仍真时失败 |
| Parallel | 显式正整数 concurrency 限制异步并发；失败或取消时取消其他任务并等待收尾 |

循环体需要多步骤时接入 Serial；Controller 基类不独立执行。每次调用的控制状态按定义、实例、运行和调用定位，终态通知后删除，不累计历史或调用树。根调用可交给 Lifecycle.run，控制子任务在该调用内收束。

当前代码装配显式登记组件类或局部执行函数，再建立实例连接；普通辅助函数无需登记。默认 bot 通过 DefaultAssembly 和 TOML 配置选择模型、工具与状态地址，不提供完整装配语言或任意执行图。

### 7.4 排序与运行控制

连接和执行依赖由实际装配表达，不从隐藏的 ctx 读写自动推导。当前排序为 priority 从小到大，同值保持连接顺序；before/after 尚未实现。

并行访问共享 ctx 不自动解决写入冲突。取消、超时、错误、结果汇总和追踪按组件实际需要实现，不要求先完成覆盖所有场景的调用契约体系。

### 7.5 生命周期与逐步断开

core 定义 config → prepare → start → stop → clean 五个生命周期插槽。各阶段整体推进：所有 config 完成后才进入 prepare，所有 prepare 完成后才进入 start。config 由配置服务加载和校验，prepare 创建资源，start 开放入口。正常退出按以下顺序执行：

1. 停止接收新的工作。
2. 让在途工作完成或按组件约定停止，逐步结束工作组件。
3. 全部 stop 完成后执行 clean，关闭组件资源、解除连接并完成最后状态写入。
4. 在存储仍可用时完成最终落盘。
5. 关闭存储并释放剩余资源与内存。

关闭顺序依据实际依赖确定，不机械地要求所有资源统一按反向表格顺序关闭。最终落盘是宿主应保证的收尾步骤，不完全依赖某个可禁用 stop handler 的优先级，也不要求每个内置收尾动作拥有公共 ID。

生命周期按显式依赖执行 config/prepare/start，按反向依赖执行 stop/clean；启动失败清理已进入阶段的组件，包含部分配置或准备失败的组件。成功的 stop/clean 处理器不在重试时重复执行。Lifecycle.run 跟踪根调用，组件自行创建的任务由所有者收束。停止或最终落盘失败报告错误并保留可重试资源，不能假报正常退出；新增 HTTP 客户端和工具任务时再验证其取消与关闭边界。

### 7.6 默认 ReAct 与扩展

aurora_agent 提供 ReActAgent 和 prepare、infer、act、observe、finish、error 六个阶段插槽。ReActDefaults 将上下文构建、ModelCall、响应解释、ToolExecutor 与观察接纳显式连接到工作阶段；finish/error 可不连接处理器。ModelCall 的组件定义为 `org.aurora.agent:handlers/model_call`。

ReActAgent 负责一次激活内的迭代、决策和终止，循环上限为正整数；控制组合只负责外层调用结构。AgentRuntime 管理提交、激活、等待和取消，通过宿主提供的 agent 获取、执行和占用查询接入；运行句柄仅存在于进程内。默认装配在启动后绑定 runtime；恢复出的中断运行标记为 failed，不自动续跑。

引导采用实例级 inbox、progress 和 runtime 地址，宿主通过 StateBinding 与 InstanceStateBinding 提供。默认过程在推理前接纳引导，在结束前检查待处理输入。工具执行由 agent 提供，多模型选择与聚合、agent 通信由 bot 扩展装配；MCP 通过adapter 包的 mcp 模块接入世界来源与 agent 工具接口，模型执行使用注入的 ModelClient；core 不增加对应业务机制。

### 7.7 直接交流与世界输入

输入按交流性质分为两条路径。面对面交流已表达“请目标 bot 关注这条输入”，由产品入口直接提交引导；外部消息与环境变化进入 world，由 cadence 形成引导。首版默认 Panel/TUI/CLI 的交互为直接交流，外部来源走世界路径；平台本身不永久绑定一种语义。直接交流记录无需先写入世界，world 也不承担全部用户对话存储。

```text
面对面交流 ──→ bot 直接交流入口 ────────────┐
                                          ├──→ 同一 AgentRuntime ──→ ReActAgent
外部消息/环境变化 ──→ world ──→ cadence ──┘
```

| 职责 | 归属与边界 |
| --- | --- |
| 世界输入与记录 | `aurora_world` 接收并保存带来源身份的消息，提供可读取记录和可观察状态；不要求消息具有 bot/run 身份，不决定唤醒谁 |
| 从世界形成引导 | cadence 位于 `aurora_bot/cadence/`，作为可选插件显式启用；根据配置选择订阅范围和目标，向既有 AgentRuntime 提交 |
| 直接交流与装配 | `aurora_bot` 提供直接交流入口，选择来源、cadence、运行与回复策略；CLI/API 接收其声明，client 承担明确的传输 |
| 执行与调度 | `aurora_agent` 保持来源无关；每个实例只有一个 AgentRuntime 调度所有者，直接交流和 cadence 共用其提交/取消行为 |

首版 cadence 对订阅范围内的世界消息原样转发：一条消息形成一条引导，保留内容与来源关联，暂不做语义聚类、合并或延迟调度。消息身份、重复识别、消费位置和转交回执用于可靠交付；来源消息、世界记录、引导、run_id 与 execution_id 分别管理。世界消息可能在一个已有运行中被接纳，不假设一条消息对应一个独立 run。

cadence 另提供显式 `[decision]` 模式：受控随机时钟持续采样业务视图，类型化选择模型决定继续观察、关注近期事件或检查未归档笔记。ctx 有效变化提高活动度，默认活跃下限 5 秒、静默中心 180 秒、活动半衰期 60 秒，间隔随机浮动 20%；内部反馈逐次减半，低于 0.01 后停止加速，外部刺激可重新增强。判断串行且有超时，不再设置固定引导冷却；随机数只控制采样时机。ChoiceClient 和 LiteLLM 决策协议在 adapter.model 中，bot 持有独立决策客户端并管理生命周期，不新增 agent 调度所有者。模型只返回固定选项，bot 以固定模板携带观察材料形成引导，继续经原 AgentRuntime 投递。

决策视图只读取所选来源的近期事件、环境及已启用的本实例笔记和行动证据；不读取完整聊天历史、配置或凭证。完整 ChoiceRequest 有 JSON 字符预算，材料截短和省略沿用 BusinessContextView。决策观察是有界窗口，不承诺历史事件逐条补发。已投递批次的事件位置与环境锚点抑制重复材料引导，笔记复查由选择模型判断；observe 不消费事件或标记业务完成，无新事件时仍可判断是否检查笔记。

决策模式复用 cadence 状态 ID，以 version=4 分开保存观察位置、最近判断、事件引导位置、最后投递时间、待核对引导及最近 64 条回执和材料引用。恢复 pending、投递不确定或回执保存失败均暂停，不自动重投；供应商错误和非法答案暂停为 DecisionFailed。原样转发使用 version=3；跨模式启动明确拒绝，用户数据不自动转换。两者的回执都由宿主异步快照保存，不保证崩溃下恰好一次。配置与试用边界见[决策 cadence 指南](START.md#决策-cadence受控随机时钟与类型化判断)。

world 的事件数据库与 ctx 变化通知配合使用，cadence 按数据库位置重新读取事件；瞬时通知不承担历史补发。来源插件只提交来源身份、消息身份与原始载荷，存储和 ctx 呈现由 world 统一管理。恢复状态不代表透明续跑或工具动作可重试。

- `aurora_world` 仅依赖 core。宿主创建 `WorldRecords(ctx, storage)` 并显式注入 WorldSources、配置组件和 cadence；对象不进入 ctx 或全局注册表。构造不打开资源，记录组件在 prepare 阶段打开 `namespaces/ns-org.aurora.world/events.sqlite3`，在 start 启动呈现刷新，stop 等待刷新任务结束，clean 关闭数据库。普通事件逐条事务提交后才发布 ctx 视图；数据库失败不消费序号，视图失败可凭相同消息重试修复。
- source_id 标识来源实例及消息身份作用域，message_id 在该来源下稳定；同身份同内容返回原记录及 `duplicate=True`，不同内容抛出 MessageConflictError。去重覆盖数据库完整历史，不受近期呈现裁剪影响。载荷必须为严格 JSON，凭证由来源在提交前排除。
- `get(source_id=..., message_id=...)`、`get_by_id(record_id)` 查询完整事件，`read(after=..., source_id=..., limit=100)` 按数据库递增序号分页返回副本。`WorldPosition(journal_id, sequence, record_id)` 绑定数据库和记录身份；错库、超前、错误锚点以及旧日志迁移前已存在的裁剪缺口仍明确报 CursorError。
- `read_content(journal_id=..., record_id=..., offset=0, limit=4000)` 在核对数据库身份后直接查询原始 JSON 片段，返回不可变 WorldContentPage，含位置、来源、消息、接收时间、text、total_chars 和 next_offset。offset/limit 按 Unicode 字符计数，单页最多 65536；拼接所有 text 后才构成完整 JSON。错库抛 CursorError，缺失记录抛 KeyError，超出全文长度抛 ValueError；等于长度返回空末页。接口不反序列化完整载荷、不刷新 ctx 或消费记录，仅支持事件归档。
- `org.aurora.world:state/records` 使用全局地址，v3 结构包含 journal_id、latest_sequence 和近期文本 records；每条有 sequence、record_id、source_id、message_id、received_at、text、abridged。默认仅展示接收时间最近 3600 秒，按新到旧累计 32000 字符预算，以完整条目停止，允许边界条目浮动。单条正文超过 8000 字符时显示标记及预览，可凭 record_id 查询原文；元数据计入预算。来源时间保留在原始载荷，不决定窗口。
- 时间和天气属于环境观察，保存在 `org.aurora.world:state/environment`，按 source_id 定位；时间默认最新 1 条，天气保留最新已发布观察及一小时内历史、合计最多 4 条，不进入普通事件数据库，cadence 单独记录各环境来源的消费位置。WorldSources 按内置环境定义选择呈现规则；自定义来源可在 world 的 sources.presentation 显式选择 events/time/weather。来源工厂不声明 retention，也不接触 ctx。
- 保留预算统一配置于 `org.aurora.world/config.toml` 的 `[view]`，普通视图和环境观察随有限 ctx 快照保存，启动以数据库重建普通视图、清理过期天气。默认每 30 秒及每次接纳时刷新，无新输入也会过期；恢复需同时保留数据库与 ctx 快照。ctx 修改不会改写事件历史，消费位置由消费者保存。
- 消费者先订阅 RECORDS 再从数据库读取；窗口裁剪不会丢失积压事件。首次 cadence 消费从数据库可用历史开始。cadence 接纳全部事件和环境来源，环境按当前保留观察及独立锚点消费；需要可靠历史归档的来源应显式使用 events 呈现。
- 默认 bot 在每次 ReAct prepare 刷新并读取近期事件、环境状态及已启用的本实例工作笔记，生成 system 之后、历史之前的临时 user 视图；来源、时间及引用随内容保留，视图不进入持久历史。bot 的 `[context_view]` 控制启用、事件/环境/笔记/行动证据选择和完整视图字符预算（默认 12000），不限制整个模型请求或裁剪归档。agent 只接收通用同步回调，不依赖 world；直接交流与 cadence 的原始引导契约保持不变。
- `[notes] enabled=true` 将 notes_read/write/list 接入既有工具执行器，不要求 world；默认 false。笔记以 org.aurora.bot:state/notes 按 instance_id 持久保存，使用版本校验防止过期覆盖。active 笔记不按事件窗口过期，archived 仍保留并占容量；关闭、恢复及取消不自动执行记录中的计划。
- `[archive] enabled=true` 将 world_read_event 接入既有工具执行器，默认 false；复用已显式装配的 WorldRecords，不创建独立连接、后台任务或 world 服务。工具按 journal_id/record_id 核对引用并分页返回原始 JSON，明确区分错库、缺失及越界；不查环境观察或工具调用，不消耗或重放事件。max_chars 默认 8000，限制每页完整 value 的 JSON 长度，不限制累计工具历史或整个模型请求。存储、引用、预算和错误边界见[主动上下文设计](aurora_bot_ctx_prompt_design.md)。
- `[actions] enabled=true` 接入 ToolRecorder 和 actions_read，默认关闭。工具批次引用、调用开始和原始结果在 bot 自有 SQLite 数据库独立事务记录；默认视图包含最近 16 次调用摘要，按 run_id/call_id 分页查询全文。记录按实例隔离，重复引用拒绝执行，取消及丢失结果保留 unknown，不因恢复或笔记声明自动重试；completed/failed 只表示工具返回。资源由默认装配持有，不反向引入 agent 对 bot 的依赖。详细语义见[行动证据](aurora_bot_ctx_prompt_design.md#已实现的行动证据)。
- `[input_budget] enabled=true` 启用统一模型请求的文本 JSON 字符上限及 10 MiB 内嵌文件上限，默认 false、max_chars 默认 128000。每次 prepare 保留 system、当前观察、全部工具定义及最新交流段，仅省略较早的完整交流段，省略提示也计入预算；必要内容放不下时在模型调用前明确失败。持久历史和已执行结果保持原样，恢复或显式重试不重复执行工具。ReActContext.exchange_ends 以消息数记录正常 stop 边界，包括空回复；该元数据不进入模型请求，宿主裁剪历史时同步平移。旧快照只重建已有 assistant 回复能证明的边界。字符预算不等同于供应商 token 或 HTTP 大小，详见[完整请求字符预算](aurora_bot_ctx_prompt_design.md#已实现的完整请求字符预算)。
- v1/v2 ctx 日志启动时明确要求迁移，不自动覆盖用户数据。停机后执行 `uv run --locked python -m aurora_world.migrate --root <数据目录>`，备份原快照，逐条导入已有记录并保留日志、记录、序号和裁剪锚点。旧日志没有通用接收时间，迁移时以导入时刻作为 received_at；已有环境记录也原样归档，新环境采样只进入环境状态。旧来源配置中的 retain_count/retain_seconds 须手动移至 `[view]` 的 time_count/weather_count/weather_seconds，模板不覆盖已有配置。

最小进程内使用方式（显式内存数据库；持久宿主传入 StorageService）：

```python
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context
from aurora_core.discovery import load_plugins, register_plugins
from aurora_world import RECORDS, WorldRecords

registry = bootstrap()
register_plugins(registry, load_plugins(enabled=["aurora_world"]))
ctx = Context(registry)
world = WorldRecords(ctx)
world.open()
changes = []
handle = ctx.subscribe(changes.append, key=RECORDS, location={})
try:
    receipt = world.append(source_id="workshop/sensor", message_id="1", payload={"text": "门已打开"})
    assert world.get(source_id="workshop/sensor", message_id="1") == receipt.record
    assert world.read(after=receipt.record.position) == ()
finally:
    ctx.unsubscribe(handle)
    world.close()
    ctx.close()
```

M4.W3 已提供 `aurora_bot.cadence` 可选插件，不自行创建第二个激活调度循环，不绕过 AgentRuntime 写入 inbox/progress。DefaultAssembly 在登记 cadence 配置定义时装配一个转发所有者，依赖 bot 和 world 记录组件；启用 world 配置时，来源组件进一步依赖 cadence，确保先订阅再开放来源。关机先停止输入接纳，再收束来源、转发和执行资源，最终由宿主落盘。`live_workshop` 已使用正式 SourceInstance、world 配置与 cadence，直接交流走 conversation 并共用同一 AgentRuntime；示例只保留模拟来源、报告工具、观察视图和 finish 阶段的历史保留策略。

cadence 的首版 D11 转交规则如下：

- 配置复用 aurora_config，模板位于 `aurora_bot.cadence/config.tomls/cadence.toml`，复制到 `<data-dir>/config/org.aurora.bot/cadence.toml`。不再提供 source_ids 白名单；默认原样转发所有世界事件和环境变化，停用来源由 world 配置管理。配置状态不持久化，运行期修改不热装配，也不写回 TOML。插件须同时显式启用 `aurora_bot.assembly`、`aurora_world` 和 `aurora_config` 及各自依赖。
- 先订阅全局世界记录，再按位置读取；通知只唤醒读取，不携带独立的待转交队列。首次消费从数据库可用历史开始，此后不静默跳过裁剪缺口。按全局记录顺序扫描，每个环境来源另存消费锚点；每条新记录的 payload 原样传入同一 AgentRuntime.submit，不加前缀、不合并，不等待业务完成。取消期间的明确写入前拒绝会等待原运行收尾再读取；取消运行不永久停用 cadence。
- `org.aurora.bot:state/cadence` 按 `location={"instance_id": ...}` 持久保存 version=3、完整事件 position、environment_positions、pending、receipts 和 error。每次提交先保存 pending 原消息，再同步提交；成功回执与新位置一次写入并清除 pending。回执保留原消息、guidance_id、引导 sequence 和 run_id；接纳不代表业务完成。正常恢复不会再次提交已关联记录，尚未转交的保留记录可以继续形成新引导。
- 提交异常、回执保存失败或恢复出 pending 均以 `TransferUncertain` 暂停；日志缺失、换代、锚点不符或裁剪缺口以 `CursorInvalid` 暂停。显式激活占用且没有 Runtime 句柄时为 `RuntimeBusy`，其他转发故障为 `ForwarderFailed`。诊断只使用固定代码，暂停不影响直接交流，重启不自动清除。首版不提供自动核对、重置游标或重放操作；恢复流程由宿主明确审核，不能凭相似文本或残留运行状态推断转交成功。
- pending、回执和 inbox 随宿主异步快照保存，普通世界事件独立事务入库，提交过程没有异步等待，但不构成外部副作用的持久事务；崩溃可能回到较早快照，不能宣称恰好一次执行。来源去重覆盖 world 数据库历史，呈现裁剪不会生成新的来源消息身份。首版完整保存关联及原始载荷，不自动裁剪；大规模日志与人工核对工具留待后续。

M3.6 的直接交流不依赖 world/cadence。M4-W 已以模拟来源验证记录、原样转发、两条路径并存和关闭恢复；复杂聚类、子代理及真实平台连接按后续切片扩展，不提前创建独立 cadence 包。

Bot 自身控制通过 `[self_control] enabled=true` 显式装配，默认关闭，不新增插件。bot_status 查询运行与自动活动，bot_autonomy 暂停/恢复普通 cadence 和计划唤醒，bot_finish 请求当前 run 在本轮全部工具和观察完成后正常结束；新输入保留给既有 AgentRuntime，结束请求不持久化、不跨运行继承。直接交流始终沿既有入口，不隐式解除暂停，也不提供宿主进程停止或重启工具。

计划由 wake_schedule/wake_list/wake_cancel 管理，按 bot 实例保存到 state/self_control。SelfControl 仅持有等待到期的任务，复用唯一 AgentRuntime.submit，不要求 world 或 choice，不复制执行机制。到期提交不经过普通 cadence 的随机等待与选择判断；有效期内的计划在重启或解除暂停后可提交，过期计划保留 expired。先保存 pending 再提交，回执保留 guidance_id/sequence/run_id；恢复 pending 变为 uncertain，未知结果不自动重投。宿主异步快照不承诺崩溃下恰好一次。关闭先停止计划接纳并等待自有任务，再收束运行、工具和模型。工具参数、版本冲突与配置影响见[计划唤醒指南](START.md#bot-的计划唤醒与自身控制)。

W2.1–W2.3 已交付来源接入、声明配置、后台托管和时间/天气环境周期，MCP 仍按以下边界继续实现：

- world 已提供 SourceSpec、SourceInstance 和 WorldSources。第三方 `kind=source` 定义登记到 `org.aurora.world:registries/sources`；同一 ctx 的来源由一个 WorldSources 所有者装配，add 选择定义、固定唯一 source_id 和复制 JSON 配置，尊重当前登记接收方的拒绝规则。component 连接既有生命周期插槽，发现、登记与连接均不创建来源资源。
- prepare 调用来源工厂，传入 source_id、`emit(message_id=..., payload=...)` 及配置副本；来源返回具有异步 start/stop/aclose 的 SourceInstance。回调不能更换 source_id，工厂不接收原始 ctx；定义替换不影响已经选定的工厂。同一来源定义可以装配多个不同身份的实例，启动后不再接受新的装配。
- 进入某个实例 start 时开放其接纳入口，允许来源在启动动作中提交首条消息；prepare 期间拒绝投递。启动失败或取消会封闭全部入口，已经接纳的记录不撤销。stop_accepting 同步且永久封闭回调，连相同身份的重复投递也拒绝；重试清理不会重新开放。接口限宿主线程使用。
- SourceInstance 可提供异步 run 主循环，所有者在 start 返回后创建和监督任务；正常返回封闭该来源并标记 completed，异常或非关闭期间的取消标记 failed，只封闭该来源，不自动重启，其他来源继续工作。被动回调来源可不提供 run；自行创建的其他任务仍须由实例 stop 收束。失败来源的剩余资源在宿主关闭时释放。SourceInstance 还可提供同步 on_context_change 回调，所有者通知有效 ctx 变化并在停止接纳时退订；允许写回，来源自行合并重复刷新使反馈收敛。回调异常封闭对应来源并记录 context_update_failed，剩余资源仍由原所有者收束。
- `org.aurora.world:state/sources` 按 `location={"source_id": ...}` 提供 definition_id、status、accepting 和 error；运行状态不持久化，error 使用固定代码，不保存后台异常文本或配置。后台失败可通过 ctx 订阅观察。正常阶段依次为 preparing/prepared/starting/running、stopping/stopped/closed；completed 或 failed 表示运行结束，收尾更新阶段但保留 error。
- stop 逆序调用实例 stop，再取消并等待托管主循环；clean 逆序释放已创建实例。关闭超时保留任务和资源供重试，不重复成功的 stop 或再次取消正在执行的 finally；全部任务退出后才释放资源和最终落盘。工厂返回前的失败/取消由工厂释放部分资源，返回后由所有者托管，接纳不意味着已经保存。
- TOML 装配通过可选的 `aurora_world.configuration` 插件接入 aurora_config，安装 extra 为 `aurora-world[config]`；基础 world 仍仅依赖 core。宿主显式启用 aurora_world、aurora_config 和配置插件，并装配 configuration_component 与 configured_sources_component；后者依赖前者，在 config 阶段选择全部来源，prepare 才调用工厂。模板复制到配置目录的 `org.aurora.world/config.toml`，只补齐缺失文件，默认 sources 为空。每项声明 source 公共 ID、唯一 source_id 和 config 对象；通用结构及引用在创建前校验，来源专用参数由工厂校验。配置状态非持久化，改 ctx 不写回文件，也不热装配来源。
- 环境周期负责产生观察，cadence 决定如何形成引导，AgentRuntime 负责执行。W2.3 的 `aurora_world.environment` 可选插件提供 time/weather 两个来源，`aurora-world[environment]` extra 引入 config/httpx，基础 world 保持仅依赖 core。时间按宿主本地时区采样；天气使用配置中的地点标签、经纬度和请求超时，经 [Open-Meteo](https://open-meteo.com/en/docs) 读取当前天气模型数据，记录提供方、有效时间、摄氏温度、WMO 天气代码与描述、km/h 风速。天气仅在首次、温差超过 temperature_change_c（默认 3°C）、天气代码或可用状态变化时发布，温差以最后已发布观察为基准；时间主动更新间隔服从均值 1800 秒、标准差 300 秒、范围为均值 ± 三倍标准差的截断正态分布；ctx 变化时另行刷新时间，同一秒合并，且不重置主动采样期限。时间 payload.trigger 标记 startup/context/rhythm；随 ctx 刷新的时间在决策模式中按衰减反馈参与节律，原样转发只投递主动时间观察。天气查询间隔 900 秒；相对等待从本次观察完成后开始，不追赶错过的周期。
- 每次采样使用启动会话和计数作为 message_id，表示新的观察，不将轮询当成外部事件修订；重启不补发离线周期，也不将同一有效时间的天气误判为完整事件历史。天气超时、网络/HTTP 错误或无效数据形成不可用观察，不影响时间来源；当前请求不重试，下个周期重新采样。关闭取消在途请求并等待主循环退出，之后关闭 HTTP 客户端。来源参数不保存凭证，天气载荷保留来源归属。
- 默认 bot 增加 world/config 的包依赖，但仍须显式启用 world 插件。登记 world 配置定义时，DefaultAssembly 连接一个来源所有者；配置选择先于所有 prepare，bot 及可选 cadence 就绪后开放环境输入，关闭时先收束来源再关闭转发、bot/模型。没有 world 配置定义时保持原装配行为；只有显式启用 cadence 并选择来源才自动形成引导。`scripts/bot.py` 默认启用完整产品插件并开放世界记录、来源状态、消费状态和暂停诊断，复用 TUI 状态页观察；来源由 world TOML 配置，cadence 接纳全部来源。
- 可运行的程序及 TOML 装配恢复夹具见 [world_roundtrip.py](../../../tests/fixtures/world_roundtrip.py)，后者使用 `--configured`；环境来源的行为和宿主恢复分别由 [包级环境测试](../../../packages/aurora_world/tests/unit/test_world_environment.py) 与 [默认环境集成测试](../../../tests/e2e/test_default_environment.py) 验证，使用模拟天气传输。模拟来源、自研环境周期和 MCP 来源共用已有入口，不增加另一套来源事件总线。
- M4.B1 已提供可选 `aurora-adapter[mcp]` 与 `aurora_adapter.mcp` 插件。`MCPClients` 在 config 阶段选择声明，prepare 阶段创建连接；每个 SDK 上下文由同一后台任务进入与退出，消费者通过异步借用上下文使用。stop 封闭入口、取消并等待剩余借用，clean 在依赖者清理后关闭客户端，最后由宿主落盘。关闭等待超时或取消可再次等待，不重复取消正在收尾的任务；真正的关闭失败阻止宿主假报关闭成功。基础 adapter 仅依赖 core，MCP extra 引入 config/SDK/httpx2/tomli-w，无 world/agent/bot 依赖。
- MCP B5.1 使用 schema_version=2、默认空 servers 映射，服务名直接作为 connection_id；模板只补缺失文件。声明支持 local/remote、协议策略、所需能力、四类超时和 headers/environment 环境引用；B5.2–B5.3 已支持 remote/local 的 legacy/auto/固定新版协商；local 在 prepare 解析显式 workspace_root 下的 cwd 和环境，按参数数组启动自有进程。stdio 单帧限制 4 MiB，stderr 丢弃，关闭回收所属 Job/进程组。旧 connections/tools 布局须通过 python -m aurora_adapter.mcp.migrate 生成候选并显式应用，保留旧身份、工具别名与暴露范围，不覆盖用户文件。凭证在连接创建时单独解析，不进入 TOML、ctx 或快照。URL 不接受 userinfo、查询串或片段；服务端任意元数据不写入观察状态。配置与状态均非持久，固定错误码区分启动超时、协议/能力拒绝、传输和关闭失败。ready 不是持续健康探测，断线在请求时诊断，不自动重放请求或重连。
- SDK 锁定 2.3.0，legacy/auto 复用公共 Client 协商入口，固定新版仍显式请求 server/discover 后 adopt；只接纳 2025-11-25 与 2026-07-28。HTTP 鉴权失败、5xx、重定向和损坏 JSON 明确拒绝，协商共用 startup 总预算；未知必需能力在配置阶段拒绝，服务端额外能力不冒充已支持能力。未提供采样、roots 或 elicitation 回调，多轮输入结果不自动续发。客户端不自动读取工具/资源、监听通知或激活模型；MCP 产品装配通过可选插件显式选择。独立本机验收与宿主用法见[启动指南](START.md#mcp-独立客户端验收)。
- M4.B4 已通过 `aurora_adapter.mcp.world` 插件与 `aurora-adapter[mcp-world]` extra 提供资源通知来源。mcp_world_component 复用 world 的声明配置与唯一来源所有者，并依赖注入的 MCPClients；来源 start 等待 subscriptions/listen 确认全部选择，后台任务同时接收通知与处理有界队列，停止只释放自身订阅和借用。世界消息通过固定 source_id 的 emit 接纳，world 不反向导入 SDK 或 agent，MCP 产品装配通过可选插件显式选择。
- 每个资源按精确 URI 配置 notification/resource/event 模式。前两种分别只存变化提示或读取内容，都使用本地观察身份；event 读取单个文本资源中的严格 JSON `{message_id, payload}`，连接、URI 与稳定 message_id 共同限定去重身份，不将采样时间混入事件载荷。身份缺失、同身份异文、未选 URI、读取失败、超限内容或缓冲溢出均使对应来源失败，其他来源和客户端仍可用。工具目录通知只设置 tools_dirty，不进入 world、不热改工具集合；协议控制通知不作为业务输入。
- SDK 2.3.0 的通知流会合并尚未消费的同 URI 提示，且有自身的 1024 项不同事件积压上限；SDK 流丢失统一报 subscription_lost。适配器另有默认 64 项的有界队列，溢出明确报 buffer_overflow。两者均不承诺完整事件日志或历史补发；资源读取反映读取时当前值，不保证保留通知时的版本。正常停止也会报告已收到但尚未接纳的观察数量，状态非持久，固定诊断同步进入宿主日志；它们不会被伪报为已落盘或在重启后重放。[SDK 订阅说明](https://py.sdk.modelcontextprotocol.io/client/subscriptions/)。
- 来源有稳定事件 ID 或修订号时用于构造 message_id；只有资源 URI、最新内容或通知到达时间时不承诺跨重连去重与完整历史。缓冲须有界，溢出或来源失败必须有明确状态；断线后不静默补发未知业务，不自动重试结果不明的工具动作。
- M4.B2 已通过 `aurora-adapter[mcp-tools]` 和 `aurora_adapter.mcp.tools` 插件接入 agent。v2 服务内 tools.include/exclude 选择远端名称，aliases 映射本地名称；默认通配自动发现并生成 v2 稳定名称，可用显式别名保留身份；无 tools 能力且没有显式选择要求的服务不登记工具。MCPTools 在 prepare 分页发现并原子登记 ToolSpec，名称/schema 冲突或选项缺失阻止启动。DefaultAssembly.components(depends_on=...) 保证发现先于模型与工具检查；实例 ExecutionPlug 接入 ToolExecutor，保留 before_call/after_call、参数校验、超时与取消。结果保留 MCP 内容块和 structuredContent；ToolExecutionError 使业务失败仍保留 JSON 内容，协议错误、超时、无效结果和结果未知使用不同错误码。调用使用 SDK session 的单次请求，不因 HEADER_MISMATCH、断线或额外交互重发。工具目录变化须重建宿主，不热改集合；外部真实服务兼容性验证尚未进行。
- MCP 客户端由独立生命周期组件持有，世界与工具桥只持有使用引用。配置完成后创建资源，消费者就绪后开放输入；停止接纳后结束来源与运行任务，待依赖者清理完再关闭客户端，最后由宿主落盘。单个来源停止不能关闭在途工具仍使用的客户端。

通用接入的下一阶段设计见 [MCP 通用接入需求与设计草案](mcp_unified_access_design.md)：由 Aurora 自身支持 HTTP/stdio，独立选择协议策略，提供按服务名配置、运行期凭证和可选产品装配。B5.1–B5.3 的 v2 配置、运行期引用、显式迁移与 HTTP/stdio 传输已交付；内部按声明、凭证、传输、协商、错误与所有权分工，stdio 管道与进程管理单独成模块，工具目录与执行已分模块并支持自动名称，可选产品装配及一次性预设已完成，业务事件扩展与可靠投递单独设计。

B3 已完成 HTTP、stdio、混合连接的共享关闭与失败回收验收，W3 最小 cadence 已实现；W4 live_workshop 与双路径集成已交付。详细切片、边界和验收见[计划第 8.2、8.5 节](plan.md#82-m4-b最小-mcp-扩展)。

## 8. 模型适配与绑定

`aurora_adapter.model` 提供 ModelClient/ModelFactory 协议、JSON 请求/响应/流式片段、能力声明、ResponseBuffer 与确定性 FakeModel。插件登记 adapters 注册表、model_client 服务与四个模型 schema。LiteLLM 适配器已实现并按需启用；FakeModel 无需网络或密钥，没有独立 adapter ID。

装配选择适配器、连接配置和逻辑模型角色，创建服务实例并注入组件。同一服务定义可以绑定多个实例，不通过修改公共服务 ID 区分具体模型。模型 profiles、角色 bindings 与默认 bot 配置使用包内 TOML 模板；用户文件位于 `<data-dir>/config/<命名空间>/`，只复制缺失文件并保留用户内容。凭证只保存环境变量名称，运行期解析且不写入 ctx。

ModelClient 提供异步 complete、通过 async with 消费的 stream，以及 aclose。ModelFactory 异步接收 ModelConfig 和单独的 api_key 参数；工厂加载与角色绑定恢复已接入默认装配。能力包含 streaming、tool_calls、file_input；聊天模型默认视为多模态，file_input 可显式关闭。能力不足明确拒绝，不自动降级。Message.content 可为字符串或 text/image_url/file 内容块；模型响应和片段独立承载 reasoning_content 与可回传的 thinking_blocks，工具往返及恢复保留原始思考与签名。profile 可设置 thinking 和 reasoning_effort，未配置时使用供应商默认。DeepSeek 使用 OpenAI 兼容传输以保留结构化输入，避免 SDK 的目录型内容裁剪。SDK 类型不上泄，不增加独立工厂 schema ID。

模型数据使用 TypedDict 表达普通 JSON。文本按 text chunk 增量输出；工具名称与 JSON 对象参数由适配层组装成完整 ToolCall 后输出，bot 不接收半截 JSON。ResponseBuffer 只保存累计结果，要求唯一且最后的 finish，缺失结束片段明确失败。结束原因区分 stop、tool_calls、length、content_filter，不将模型响应结束等同于对话完成。

`aurora_agent.model` 的 ModelCall 从约定 ctx 地址读取请求，在同一输出地址更新 status、execution_id、text、tool_calls、finish_reason。失败或取消保留已收到的部分文本并标记 failed/cancelled，错误继续传播，不保存片段历史。完整响应接口在返回前不提供部分文本。

单次响应流由调用组件关闭；共享客户端由创建它的装配在所有调用结束后关闭。同一输出地址须串行调用，组件不保证共享客户端任意并发安全。ModelCall 的 completed 只表示该模型请求完成，工具执行与下一轮推理由后续装配实现。连接配置与绑定恢复沿用 TOML 和状态地址，不增加独立配置／秘密／对象管理子系统。

## 9. CLI、API 与事件传输

工作区快捷启动使用 `aurora bot/panel/tui` 或 `pnpm bot/panel/tui`，共同调用 `scripts/` 下的对应 Python 脚本。CLI 将其登记为非运行期工具命令，只定位工作区并透传参数，不导入 Bot 装配；脚本分别维护完整产品入口、Panel 开发入口和 TUI 环境加载。前端快捷命令不隐式启动后端，源码工作区之外须通过 `--root` 指定脚本所在目录。

CLI 将 argv 转为对应接口使用或操作调用，不重复实现 ctx 与 bot 行为。bot 可以在自己的命名空间声明命令、端点等入口，引用 CLI/API 的公开注册目标；这不要求导入或安装它们的实现。

当前 CLI 提供 ctx 读写、观察、`id list`、`run` 和 bot 的 `run submit` / `run activate` / `run cancel`。`run` 启动选定装配后等待取消；提交类命令在本次进程内完成一次提交、等待运行收尾并输出流式 JSON，然后退出。远程 ctx 访问与 M3.6 直接交流已实现；`serve --endpoints` 显式开放产品端点，API 回执与运行关联见第 10.2 节。

API 为 client 提供后端连接和 ctx 访问所需传输，不作为插件扩展总线。API 可以提供明确需要的额外端点，但不预设统一的任意 operation 远端调用系统，也不要求先经过 CLI 描述才能实现 ctx 传输。

URL、HTTP 方法和 WS 消息由具体端点实现描述，不从 ID 自动推导。一个端点可以提供多条绑定，按实际需要说明各自的传输入口和处理目标；不强制为每个端点新增正式 schema ID。

core 的事件机制负责进程内发布订阅，ctx 变化订阅属于 ctx 接口；client 封装界面需要的订阅与连接管理，API 承担事件传输。沿用原事件类型 ID，传输层可以补充请求关联、来源和序号等信息，不另建同义业务事件身份。

不因存在 WS 就要求新增一组通用订阅 operation。订阅标识、取消、连接断开与重连行为在实现实际客户端需求时明确，本版不承诺事件历史补发或断线零丢失。

## 10. client 与界面

### 10.1 共享 ctx interface

| 使用方 | 接口实现 | 实际数据操作位置 |
| --- | --- | --- |
| Python 插件 | 进程内 ctx 接口 | core |
| CLI | 命令映射至对应接口 | core 或实际业务组件 |
| TUI、Panel | client 的 ctx 接口 | 通过传输到后端 core |

统一 interface 表示共享访问语义，不表示 Python 与 TS 必须导入同一份代码。client 实现对应 ctx ID 的访问入口、参数传递、结果接收和订阅；不将后端 callable、服务对象或插件执行树复制到前端。

共享传输的浏览器访问由 API 的 AccessPolicy 控制：默认仅本机非浏览器访问，显式开放来源或代理 Host 必须配置运行期令牌。HTTP 使用 Bearer，WS 使用带 access_token 的 WatchHandshake 首帧，认证通过前不创建订阅或读取状态；原 WatchRequest 仍只描述过滤条件。CORS 预检仅开放已登记路由的方法与所需头，错误来源/Host 返回 403，错误令牌返回 unauthorized。无 Origin 的原生客户端在启用认证时同样需要令牌。

后端保持 IPv4 回环监听，生产代理承担 TLS/WS Upgrade，来源与 Host 使用精确白名单，不信任转发头或通配符。认证适用于 ctx、conversation、configuration 的全部已开放路由，不改变状态键与端点授权范围。令牌不进入 TOML、ctx、快照或 TUI 偏好；环境变量名由宿主/客户端选项指定，更换令牌须重启。认证失败停止重连；网络断线重新认证、订阅、读取快照，HTTP 动作不自动重放。具体命令与部署边界见[浏览器访问指南](START.md#浏览器访问与运行期认证)。

### 10.2 界面动作边界

TUI 使用 OpenTUI，Panel 使用 Vue 生态；两者通过 client 交互，各自维护本地视图、动作、主题、键位与偏好。首版采用围绕长期存在的 bot 的工作台，展示直接交流、运行、输出和工具活动；世界能力接入后展示世界输入及其引导关联，不提前建立多会话上下文隔离。

Panel 已提供 Vue/Vite 入口、显式令牌连接、实例选择、交流与只读状态页。页面通过共享 client 订阅并刷新 ctx，模型过程、工具活动与请求回执分开呈现；终态通过 conversation query 确认，不从残留状态推断完成。网络中断仅恢复观察，接纳结果不确定时保留原请求供核对或显式重试；宿主会话更换使旧请求失效。输入令牌在开始连接时从表单清空，不进入浏览器存储或构建产物；刷新页面不自动连接、重放或取消运行。当前 Panel 尚未提供配置/ctx 编辑与偏好持久化，完整多端操作验收留待后续。

Panel 工程以 KunUI 提供按钮、输入、文本域、选择器、抽屉和状态标签，产品图标从 Lucide 的 `@lucide/vue` 按需导入。聊天居中、输入区固定，工具活动与已保存上下文通过原生 details 按需展开，公开状态作为只读页面浏览。Vue Router 使用 Hash 路由并延迟加载交流/状态页，静态部署无需路径回退；KeepAlive 保留页面筛选与滚动，Pinia 保存跨页观察状态与按后端/实例区分的草稿。应用生命周期持有唯一订阅连接，页面切换不重连；连接令牌由表单临时解析，不作为 Pinia action 的值参数或持久状态保存。

`apps/aurora_panel/src` 按以下职责组织，不在界面复制后端调度或共享 client 的传输实现：

| 路径 | 职责 |
| --- | --- |
| `App.vue`、`main.ts` | 注册 Pinia/Router、装配全局样式、应用关闭清理 |
| `router/`、`layouts/`、`views/` | 页面路由、工作台布局、交流/状态页面装配 |
| `components/connection`、`conversation` | 连接表单与消息展示；输入、运行分组和只读状态由对应页面装配 |
| `stores/` | 跨页面共享观察状态、动作入口和内存草稿，不持久化凭证或隐式重发动作 |
| `composables/` | 交流视图投影与跟随滚动；负责释放各自监听 |
| `services/` | 无界面的工作台会话控制，复用共享 client 管理订阅、回执核对、重试和取消 |
| `types/`、`constants/`、`utils/` | 工作台领域类型、公共状态 ID/标签、状态地址和值解析 |
| `theme/`、`styles/` | KunUI 品牌 token、Tailwind 入口与工作台样式；CSS 媒体查询负责窄屏布局 |

服务层保持可直接由 Node 跨进程验收，Vue/Pinia 不进入服务依赖。`vue-tsc` 启用严格模板检查，原生 `aria-*`、`data-*` 与 role 属性按组件透传处理。生产构建仅保留 `index.html` 一个入口，按页面和 Vue 依赖分块；品牌 token 独立于布局样式。

当前 TUI 已提供交流/状态页签、底部多行输入、运行分组、工具折叠、指定运行取消、ctx 筛选与精确地址编辑，以及声明 TOML 文件编辑。切页保留交流草稿与滚动位置，向上翻阅时新内容不抢占位置；关闭界面只停止观察。运行终态通过回执查询确认，断线后核对原请求，宿主重启不自动重放。连接选择可显式保存；页面与工具展开偏好只保存在客户端。

ctx 编辑复用既有 get/set/delete 及状态键白名单，写入整项替换，不是读改写事务。TOML 编辑通过 `aurora_config` 声明的 `org.aurora.config:endpoints/configuration`，宿主显式选择后才开放 list/get/save 三条 POST 路径。配置服务在 config 成功后绑定编辑入口，停止接收阶段关闭；API 不依赖配置实现，配置包也不导入 API。只允许按配置声明 ID 编辑包模板对应的用户文件，不接受任意文件路径，不包含 `host.toml` 与环境凭证文件。

保存 TOML 复用 config 阶段的结构与关联校验；原始文本完整写入临时文件后替换目标。读取修订覆盖全部声明文件，同一宿主串行保存，任一配置变化返回 409 configuration_conflict。外部文件编辑仍有检查与替换之间的竞态，不承诺跨进程原子比较或跨文件事务。保存成功只返回 restart_required=true，不热更新 ctx 或重建模型/工具；资源创建仍由下次启动负责。ctx 与 TOML 修改均先显示目标和草稿再确认，网络结果不确定时保留草稿并要求重新读取，客户端不自动重发。

直接交流由 bot 的专用产品入口接收，复用现有 run 提交与取消操作；API 只接收明确的传输绑定，client 关联目标实例、消息回执、引导与运行。通用 ctx 写入不隐式触发交流，不提供任意 operation 的远端转发，也不为该路径新增 conversation/send、conversation/cancel 同义操作。

D10 已确定：空闲提交可启动一次运行，运行中提交作为引导保留当前 loop 和既有结果；接纳回执不表示任务完成，也不承诺 bot 必须回复。停止作用于指定 instance_id/run_id，取消须等待收尾；关闭或断开界面仅停止观察，不取消运行或永久停用来源/cadence。首版不把模型过程输出自动等同于对外回复。

M3.6 已登记 `org.aurora.bot:endpoints/conversation`，由 API 按宿主显式选择绑定四条 POST 路径：`/conversation/info` 返回当前 session_id 和已绑定 instance_ids；`/conversation/submit` 接收 session_id、instance_id、request_id、text 和可选 files；files 的每项含 name、media_type、base64 data，最多 8 项、合计 10 MiB，附件存在时 text 可为空。支持图片、PDF 和 UTF-8 文本，文件参与回执冲突检查；该端点单独允许 15 MiB HTTP 请求体，其余端点保留原限制。`/conversation/query` 按前三项查询；`/conversation/cancel` 按 session_id、instance_id、run_id 取消并等待清理。bot 不导入 API，API 不导入 bot，端点复用同一 RunOperations 和 AgentRuntime。未开放端点时没有对应路由。

接纳回执包含 session_id、instance_id、request_id、guidance_id、sequence、run_id、accepted=true；重复提交相同身份、文本与附件返回同一回执，改变文本或附件返回 409 request_conflict。不同 request_id 即使内容相同也属于新引导。去重作用域为当前插件会话和 bot 实例；回执最多 4096 条，不淘汰旧身份，达到上限返回 429 receipt_limit，旧消息仍可查询。回执只留在内存，不混入业务快照；重启后旧会话返回 409 session_expired，不能将换会话重发解释为安全重试。

查询额外提供 run_status（pending/completed/cancelled/failed）和 error；pending 包括排队、执行和清理，终态只取自运行句柄，不推断残留 ctx 状态。该状态属于关联的运行，不承诺每条引导已完成业务或已对外回复。取消未知或已结束的 run 返回 cancelled=false；终态后的清理仍须等完。取消期间的新引导返回 409 busy，未启动或关闭中的实例返回 503 unavailable。HTTP 结果不确定时保留原身份查询；同会话下未知回执返回 404，重试也必须沿用相同身份与内容。客户端从不自动重发动作，关闭连接只结束观察。M3.6 不依赖 world/cadence。

### 10.3 按需生成

跨语言实际使用的数据结构以维护的后端公开描述为来源，可以从 Python 类型、Pydantic、OpenAPI 或 WS 描述生成 TS 类型与 ID 常量。只导出需要且可传输的部分，不要求将全部 Python 登记项导出给客户端，也不强制每个局部接口加入生成链路。

当前本机 ctx 协议由 [aurora_api.contract](../../../packages/aurora_api/src/aurora_api/contract.py) 描述，直接交流由 [bot 契约](../../../packages/aurora_bot/src/aurora_bot/conversation_contract.py) 描述，声明 TOML 编辑由 [config 契约](../../../packages/aurora_config/src/aurora_config/editor_contract.py) 描述。`uv run --locked python scripts/generate.py` 显式合并三者，生成 client 的 JSON 描述、TS 类型和绑定常量；增加 `--check` 可只读检查产物。API 独立导出仍只包含 ctx，不要求安装 bot 或 config。生成不启动宿主，不导出业务配置或模型 SDK 类型。共享 CtxClient 提供 ctx 访问、订阅、conversation.info/submit/query/cancel 与 configuration.list/get/save；重连先订阅再重新读取状态，刷新期间有界缓存变化，界面可观察连接及刷新状态。多次 HTTP 读取不构成原子快照，客户端不重放 HTTP 动作，也不将本地关闭解释为取消 agent。

开发时可使用 Vite 代理 API，生产环境优先同源部署。认证采用运行期令牌和显式来源/Host 白名单，部署方式见浏览器访问指南。同源安排不代替访问控制。docsite 与 landing 独立构建。

## 11. 依赖方向与目录

代码依赖和 ID 引用分别表达：引用一个接收方的公开 ID 不要求导入它的实现；缺少接收方按未连接告警规则处理。显式使用某个 Python 协议类型时，才建立对应代码依赖。

| 使用方 | 代码依赖方向 | ID 引用与连接 |
| --- | --- | --- |
| `aurora_core` | 通用基础依赖 | 不依赖业务包；维护当前后端总表 |
| `aurora_config` | core | 提供配置声明、校验、模板与 config 阶段服务 |
| `aurora_control` | core | 提供执行契约、控制组合与控制状态 |
| `aurora_agent` | core、control、adapter.model | 提供 ReAct、模型调用、工具执行与运行调度 |
| `aurora_bot` | core、control、agent、adapter.model | 可声明面向 CLI/API 的入口，不硬依赖其实现 |
| `aurora_cli` | core、api | 接收已启用的命令声明，不导入 bot 插件实现 |
| `aurora_api` | core；按实际需要复用 CLI 公开适配描述 | 提供 client 传输；不强制经过 CLI，不导入 bot 插件实现 |
| `aurora_logging` | core；按实际需要 | 当前提供日志配置 |
| `aurora_world` | core；config/environment extras 提供配置与环境依赖 | 世界记录已实现，不依赖 agent/bot；cadence 通过其公开记录与 ctx 订阅接入 |
| `aurora_adapter` | core；model extra 引入 config，litellm 引入供应商 SDK；mcp 引入 config/SDK/传输依赖，mcp-world 加入 world，mcp-tools 加入 agent，mcp-bot 加入 bot | 客户端、世界通知桥与工具桥已实现；world 不反向依赖 adapter；agent/bot 使用模型模块，不依赖 MCP 桥 |
| `aurora_client` | TS 传输与所需生成类型 | 实现统一 ctx 接口和既有 ctx ID 入口 |
| `aurora_tui`、`aurora_panel` | client | 使用 ctx interface，不参与后端插件装配 |
| `docsite`、`landing` | 各自构建依赖 | 独立解析页面和资源 |

Monorepo 使用 Python `uv workspace` 与 TypeScript `pnpm workspace`，Python 包采用 src-layout。

| 路径 | 内容 |
| --- | --- |
| `packages/aurora_core/` | 微内核 |
| `packages/aurora_config/` | 配置声明、校验与 TOML 加载 |
| `packages/aurora_control/` | 执行契约与控制组合 |
| `packages/aurora_agent/` | ReAct、模型调用、工具执行与运行调度 |
| `packages/aurora_bot/` | 默认装配、配置与产品入口 |
| `packages/aurora_cli/` | CLI |
| `packages/aurora_api/` | 后端传输 |
| `packages/aurora_logging/` | 日志配置 |
| `packages/aurora_world/` | 世界记录、来源身份与位置读取、来源装配、可选声明配置、后台托管与时间/天气环境来源 |
| `packages/aurora_adapter/` | model 模型协议、配置与供应商适配；mcp 声明配置、客户端生命周期、世界与工具桥；统一 config.tomls 资源 |
| `packages/aurora_client/` | TS 共享 ctx 访问与连接 |
| `apps/aurora_tui/`、`apps/aurora_panel/` | 终端与 Web 界面 |
| `apps/docsite/`、`apps/landing/` | 静态应用 |
| `scripts/` | 开发与按需生成脚本 |
| `packages/<包>/tests/`、`tests/contract/`、`tests/e2e/` | 包内维护单元和协议测试，根目录维护跨包契约、工作区和端到端验证 |

## 12. 初期非目标

- 不设计多租户运行或记忆隔离，不按插件命名空间授权内部 ctx。
- 不实现插件热插拔或进程级恶意插件沙箱。
- 不为所有对象强制创建独立 schema、契约版本或公共 ID。
- 不建立任意后端 operation 的通用远端分发体系。
- 不将 TUI/Panel 设计成后端插件宿主。
- 不提前实现完整状态分类、凭证管理、兼容证明或退出协调框架。
- 不要求初期完整 MCP、所有界面功能对齐或复杂多发行版管理。
- `aurora_playground` 继续保留为后续包扩展：消费指定实例与输入输出接口，装配输入、输出插头；本版不增加包依赖或正式 ID。

## 13. 初期里程碑

| 阶段 | 交付范围与需要明确的最小行为 |
| --- | --- |
| M0 骨架 | Monorepo、ID 格式、统一登记项与总表、自举、逻辑注册表、未连接告警；按需接口描述的表达方式 |
| M1 微内核可用 | 显式 ctx 操作及其当前用例所需行为、变化订阅、异步落盘、逐步关闭与最终落盘、插槽连接与调用、CLI 基础入口 |
| M2 最小 bot | 默认装配、控制组件、单模型 ReAct、ModelClient、LiteLLM、TOML 配置与绑定恢复、基本工具路径、运行提交与取消 |
| M3 client、API 与 TUI | ctx interface、HTTP/WS 传输、实际订阅和重连行为、需要的生成类型、界面数据范围与连接访问控制、OpenTUI 界面 |
| M4 能力扩展 | M4-W 世界记录与 cadence；多模型、agent 通信、MCP、Vue Panel、文档站与落地页 |

各阶段记录已经实现的可观察行为，避免同一接口出现互相矛盾的实现；不以冻结所有规划契约作为启动下一阶段的前置任务。消息提交与取消按第 10.2 节的已定方向实施，具体传输协议随 M3.6 验证。

当前 M0、M1、M2 已完成；M2.8 于 2026-10-31 通过整体验收。M3 已交付本机 HTTP/WS ctx、按需契约、共享 TS client、直接交流和工作台本机联调；D08 的浏览器来源、运行期认证及代理 Host 边界已交付，生产 TLS 代理部署仍须按环境验收，D09 的本机订阅/重连和 D10 的传输关联已验证。M4.W1 世界记录、W2.1–W2.3 来源装配及环境周期、B1–B5 MCP 接入与共享关闭、W3 最小 cadence 已交付；W4 live_workshop 与双路径整体验收已完成。详细依赖和验收见[里程碑计划](plan.md)。附件区分当前定义与规划身份，不表示所有对象均已加载或对外提供。

## 14. 后续讨论

1. **直接交流工作台。** 复用 M3.6 已实现的回执、重复请求、状态查询、取消和契约，交付 OpenTUI 交互，不把接纳或模型输出解释为业务完成。
2. **client 连接（D08、D09）。** 本机 ctx 与订阅重连已交付；浏览器认证、来源白名单和数据开放范围已明确，后续按实际环境验收反向代理部署，复用已有关闭和刷新语义。
3. **独立 harness。** 复用 core、adapter.model、control 与 agent，定义自己的装配、配置、资源与恢复策略、交互入口和发布边界；不复制 bot 的默认配置或 CLI 命令。
4. **世界与 cadence（D11、M4-W）。** world 的记录与来源独立于执行；bot 的可选 cadence 插件统一通过既有 AgentRuntime 提交。记录保留、重复识别、消费位置、转交结果不确定及恢复行为已验证；Bot 已提供显式计划唤醒和自身控制，子代理另行实施。
5. **公共接口维护。** 从实际边界提炼必要的 schema、兼容与迁移规则，不预设通用证明系统，不以规划 ID 证明接口已经冻结。

## 15. 变更记录

### 15.1 v0.2.3

- 执行能力拆分为平级的 `aurora_control` 与 `aurora_agent`：control 承载执行契约和四种控制组合，agent 承载 ReAct、模型调用、工具执行、默认阶段与运行调度；`aurora_bot` 保留配置、默认装配、资源所有权和产品入口。
- 公共 ID 与插件入口按包归属：control 使用 `org.aurora.control`，agent 使用 `org.aurora.agent`；发现分组为 `aurora.plugins`，运行时不提供旧导入路径、旧插件名或旧 ID 别名。
- AgentRuntime 通过宿主提供的 agent 获取、执行与占用查询连接，不再访问 `DefaultAssembly` 私有成员；运行句柄仍只存在于进程内。
- 文档基线对齐时补充 M2 已完成状态：LiteLLM 适配、TOML 模型 profiles 与角色绑定、基本工具往返、CLI `run submit/activate/cancel`、取消与重启恢复均已验收；当时 M3 与 D10 尚未开始。当前进度见第 13 节，后续变更见[变更记录](../../CHAGELOG.md)。
- 配置声明、结构校验、TOML 模板与 config 阶段服务归属 `aurora_config`；core 保留通用状态、持久化与生命周期机制。
- 明确独立 harness 的目标集合为 core、adapter.model、control 与 agent，并记录拆包边界、测试与后续工作。
- 同步包职责、命名空间、依赖方向、目录与里程碑；补充 `aurora_logging`、`aurora_world` 的当前边界。

### 15.2 v0.2.2

- core 明确维护 `Id → RegistryEntry` 内存哈希表；逻辑注册表可基于总表提供视图与接入行为，定义、实例、状态值分别管理。
- 明确可选 CLI/API 接收方缺席时保留未连接声明并告警，不因此阻断整个插件加载。
- 接口由双方按需描述，兼容性由提供插槽的一方判断；允许描述不同但兼容或缺少正式 schema 的特殊连接。
- 取消每个对象必须有正式契约的暗示；不因复核意见批量新增公共 schema、订阅 operation 或内置 handler ID。
- 明确 client 实现统一 ctx 访问入口和对应 ID 支持；插件走进程内接口，TUI/Panel 通过 client 交互，HTTP/WS 只承担传输。
- 保留既有 bot operation 与端点 ID，但移除界面动作必须调用它们的预设；消息提交与取消机制留待后续讨论。
- 状态与运行时对象管理保持待讨论，只确认需要恢复的数据落盘、运行时连接不直接落盘以及界面数据不全量导出。
- 明确类似插排逐步断开的退出顺序，最后写入完成后落盘，再释放存储和剩余资源。
- 同步依赖说明、里程碑和配套目录，沿用既有公共 ID 与 kind。

### 15.3 v0.2.1

- 明确个人单租户、唯一 bot 后端、多客户端与内部共享 ctx。
- 明确内存工作区、显式变更、异步持久化和正常退出收尾。
- 移除内部命名空间授权前提，补充目录与插件数据库边界。
- 明确插头／插槽、树形装配和插件流程控制；TUI 使用 OpenTUI，Panel 使用 Vue 生态。

### 15.4 v0.2

- 在 ctx/hook、插件发现和包边界基础上加入统一命名空间 ID。
- 区分定义与实例、插槽与处理器、命令／端点与操作。
- 完整公共 ID 表独立保存为附件。

### 本机 API 的只读观察键

宿主通过 `keys` 开放读写及订阅，通过 `read_only_keys` 仅开放 get/list/watch；CLI 对应 `--keys` 与 `--read-only-keys`，两组不得重叠。同一键的全部 location 使用相同权限；只读键的 set/delete 返回 HTTP 403 forbidden。`scripts/bot.py` 显式启用完整 MCP 产品装配，将 bot、world、cadence 与 MCP 诊断状态作为只读观察键，交流及 TOML 编辑走显式产品端点。现有 ctx 请求与响应信封不变，客户端按既有 forbidden 错误显示拒绝原因。
