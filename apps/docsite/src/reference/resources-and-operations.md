---
order: 1
---

# 资源与操作协议

## 身份、版本与域

`ResourceKey` 的规范字符串为 `namespace:domain/kind/path`。namespace 表示提供方，domain 表示语义领域，kind 表示对象类别，path 定位具体定义。例如：

| 身份                               | 含义           |
| ---------------------------------- | -------------- |
| `aurora:rhythm/model/gru`          | GRU 节律权重   |
| `aurora:memory/model/tgn`          | 时序图记忆权重 |
| `lab:example/query/echo`           | 扩展查询       |
| `aurora:bot/command/goal_set`      | 主体目标修改   |
| `lab:kernel/module/example`        | 扩展模组声明   |
| `aurora:engine/process/agent_tree` | 认知过程定义   |

`ResourceRef` 包含 `key` 与可选 `revision`。明确版本指向同一份定义，不能默认为“最新”；未指定版本时，由目录在唯一版本或显式别名下解析，有歧义时失败。终端用 `资源名@revision` 表达固定引用，序列化数据将 key 和 revision 分开保存。

内容资源的版本是原始字节 SHA256。命令和查询也可使用显式协议版本，例如目标操作的 `@2`。模组发布版本、内核 API 兼容范围和清单内容摘要各有用途，不互相替代。切换别名不会改写过去已经固定的引用。

世界 scope 与资源身份相关但不相同：`aurora:world/bot/default` 是持久主体域，`aurora:run/<tree_id>` 是认知台账域，`org.aurora.qq:world/room/1` 是应用业务域。域由提交者明确指定；目录中的 `ScopeDeclaration` 用于所有权、分类和范围解释，world 不代替业务选择域。

## 三种沟通语义

| 语义 | 入口                                       | 状态与因果                                                             |
| ---- | ------------------------------------------ | ---------------------------------------------------------------------- |
| 查询 | `OperationKind.QUERY` 或注入的只读能力端口 | 读取快照或计算推荐，不改变目标等业务状态；调用审计和可重建缓存可以更新 |
| 命令 | `OperationKind.COMMAND`                    | 请求一个逻辑处理者执行明确意图，记录请求与结果                         |
| 事件 | `WorldWriter.append_commit/append_event`   | 已发生事实进入追加世界，多方按游标或 scope 消费                        |

内部能力调用使用稳定的契约实例，跨入口的领域操作使用统一路由。事件不是字符串函数调用，也不保证订阅者已经处理；世界保存了事实不等于外部效果已成功。当前部署不提供跨机器消息代理或外部端到端恰好一次交付保证。

## 操作定义与请求

`OperationDefinition` 必须有固定 `ref`、说明和 object 参数结构；可选 `tool_name` 生成模型工具，`retry_safe` 声明中断命令在恢复时能否重新执行；只读查询可以重新计算。静态资源定义必须与实际处理者一致。

`OperationRequest` 字段如下：

| 字段             | 语义                                 |
| ---------------- | ------------------------------------ |
| `request_id`     | 来源内稳定的调用 ID                  |
| `bot_id`         | 接受此次操作的主体                   |
| `source`         | 调用来源                             |
| `target`         | 待解析或固定版本的目标引用           |
| `kind`           | command 或 query，必须与目标定义一致 |
| `arguments`      | 递归不可变的 JSON 参数               |
| `correlation_id` | 可选的关联链身份                     |
| `caused_by`      | 可选的直接因果来源                   |
| `deadline_at`    | 可选带时区期限                       |

持久调用身份由 `(bot_id, source, request_id)` 的规范编码摘要构成。相同身份必须保持参数、目标、来源、关联与期限一致；目标首次解析后固定其版本，重试不追随别名变化。主体状态的 `expected_version` 是具体命令参数，不是所有请求都必需的全局字段。

处理者通过 `scopes_for` 声明观察和发布域，通过 `execute` 返回结果。路由校验主体、定义和参数，登记 `operation.requested`，在执行前核对期限，再调用处理者并记录结果。工具适配器把 `scopes_for` 的范围交给 engine 的观察屏障；显式终端调用不启动认知，也不借此推断模型已经观察了相关事实。这项审计不能代替处理者对外部服务的幂等保护。

## 结果与恢复

`OperationResult` 包含 `data`、`status`、可选 `message`、`evidence_refs` 和大正文引用 `body_ref`。状态只有三种：

- `succeeded`：已确认成功。
- `failed`：明确拒绝或可确认未发生效果的失败，需要原因。
- `unknown`：可能产生效果但无法确认，需要原因和后续核对。

已有完成回执直接恢复，同身份不再次产生已确认效果。中断查询可以重新计算，只有声明 `retry_safe` 的中断命令允许重新进入处理者；非幂等效果未知时保留未知状态，调用方应查询真实外部状态。请求登记和最终结果是不同事实，不能把接收请求当成行动完成。长过程需要自己的实例身份与进度事实，不能依赖内存中的协程对象跨重启恢复。

正式装配对超过 64 KiB 的请求或回执先保存完整 JSON 为内容资源，再把引用写入世界。内容发布失败时不进入处理者；恢复时先核对完整正文，缺失或损坏不允许替换原请求或重复执行效果。小回执内联保存。模型与终端对大结果显示固定引用，并通过有界读取展开；收到引用不等于读过正文里的证据。

## 事实与实例

世界提交包含稳定 commit ID、kind、source、summary、data、各域序号与因果前沿，以及全局 cursor。`occurred_at` 表示事件发生时间，`recorded_at` 表示 Bot 获知时间；二者带时区并规范为 UTC。历史查询不能使用后来才获知的事实，同 ID 不能改写历史。

过程定义描述如何执行，运行实例记录 Bot、独立实例 ID 和实际定义版本。实例目录从世界投影，以固定 cursor 形成可复查的历史描述；发现结果仍需分页。`started` 只表示缺少规范终态，不能证明当前任务还在进程里执行，也不能授权自动重放。

目录、LLM 提供方和外部服务各有自己的名称边界。原生工具身份在 Provider 边界转换为协议安全别名，响应进入领域前反向映射；提供方的 `sdk_provider` 同样独立于资源路径，不能把资源对象的文本表示发送为远端模型名。

## 认知执行接口

`CognitionRequest` 携带 `message`、可选 `run_id`、Agent、世界前沿、触发事实和记忆范围；运行时补全身份与默认 Agent 后调用 `CognitionRunner.execute()`。`CognitionResult` 返回 `run_id`、`output` 和可选 `error`，`status` 从错误是否存在推导为 `completed` 或 `failed`。运行时还统计抛出的失败与中断，不保存节点图。

调用入口为 `runtime.run(message, run_id=...)`、`runtime.run_from_event(event, run_id=...)` 和 `runtime.launch(request)`；领域模块通过 `COGNITION_BINDINGS` 获取 `CognitionLauncher`。更换执行器不改变输入先入世界、运行身份唯一和未知效果不重放的要求。

持久协议的 `engine.tree.started/completed/failed`、`<运行ID>:tree:<阶段>` 提交身份、`tree_id` 字段和 `world_trees` 查询描述认知执行的历史事实，不要求执行器在内存中构建树。过程资源记录实际策略；默认过程 `aurora:engine/process/agent_tree` 使用深度优先委派。替换执行器仍须按协议登记开始与结果，并保留因果及过程版本。
