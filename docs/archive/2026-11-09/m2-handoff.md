# M2 最小 bot：实现交接

> 历史归档：2026-11-09。保留当时的设计、计划与验收语境，不作为当前功能承诺或操作指南；当前入口见 [文档索引](../../INDEX.md)。

M2 已于 2026-10-31 完成并通过整体验收；本文保留 M2 期间的交接语境，不能作为当前待办清单。当前执行包定义见 [公共 ID 目录](aurorabot-id-catalog-v0.2.3.md)，可运行入口见 [示例指南](START.md)，交付与验收范围见 [变更记录](../../CHAGELOG.md)。

## 1. 从哪里继续

M0、M1 和 M2 已完成。M2 交付的是微内核、CLI 基础宿主、四类控制组件、模型协议与假模型、LiteLLM 适配、默认装配、ReAct 工具循环、运行提交/取消以及 CLI 观察入口。

M2 的内部顺序是从确定性本地工具开始，再用假模型完成“工具请求 → 执行 → 观察回填 → 再次推理”，随后接入默认装配、真实模型、CLI 与整体验收；该顺序已完成，保留作为实现脉络。产品语义存在分歧时先询问用户，不从规划 ID 推导已批准行为。

阅读顺序：

1. [AGENTS.md](../../../AGENTS.md)：协作与编码规范。
2. 本文件与 [计划](plan.md)：当前进度、接续任务和决策点。
3. [设计文档](aurorabot-design-v0.2.3.md)：第 4、5、7、8 节的已实现边界。
4. [公共 ID 目录](aurorabot-id-catalog-v0.2.3.md)：第 5 节模型协议与第 6 节 control、agent、bot 定义。
5. [示例指南](START.md)：core、control、独立 agent、默认 bot 与持续宿主的启动方式。
6. [变更记录](../../CHAGELOG.md)：按日期及条目上下文阅读，历史描述不覆盖当前接口。

接手时先检查工作区和最新提交，保留用户改动，不重新实现已交付切片。

## 2. 已确定的组件模型

- core 提供登记、ctx、订阅、实例连接、单次调用和生命周期；控制、模型、工具、ReAct 属于插件。
- bot 组件业务数据由实例自行读写 ctx。插头与插槽握手交换 ctx 地址和可选 schema；执行只传递运行及调用身份，没有业务参数或返回值。
- 双方可以描述 schema，由插槽接收方判断兼容性；双方描述不同但被接收时 warning。局部约定可不提供 schema，不为少量特殊连接强造契约。
- 等待调用确定执行结束；ctx 变化和 EventBus 用于通知，组件也可主动订阅以触发更新。不是所有状态写入都触发执行，事件也不提供历史回放。
- 根组件控制子调用，Serial、Branch、While、Parallel 可嵌套。core 不遍历业务树、不推断隐藏的 ctx 依赖。
- 调用关系、共享服务所有权与生命周期依赖分别表达。使用共享客户端不意味着拥有关闭它的权力或可以任意并发调用。

### 2.1 定义、实例与执行身份

| 字段 | 当前含义 |
| --- | --- |
| definition_id | 完整 Id，登记为 component，指向组件类或局部执行函数 |
| instance_id | 实例身份，默认 UUID，也可显式传入非空字符串；重复取得同一组件的 plug 保持身份 |
| run_id | 一次业务运行的关联标识，父子调用共享 |
| execution_id | 单次调用身份；ExecutionRequest.child() 创建新身份并记录父调用 |
| reference | definition_id.instance_id 展示字符串；内部字段分开保存，不交给 Id 解析 |

`component_entries(definition_id, component, execute, provider=..., children=False)` 显式生成组件及其 /execute 插头定义；children=True 同时生成 /children 插槽。这是 bot 插件的声明约定，core 仍按完整 ID 与显式 kind 寻址，不根据路径推断运行时树。

示例中的局部业务函数也通过此 helper 登记，再包装为 ExecutionPlug；普通私有辅助函数不要求登记。ExecutionSlot 校验插头归属，同一插槽内子实例的 instance_id 唯一；LifecycleComponent 的 instance_id 则须在同一宿主内唯一。

### 2.2 控制接口与状态

源码：[control/execution.py](../../../packages/aurora_control/src/aurora_control/execution.py)、[control/components.py](../../../packages/aurora_control/src/aurora_control/components.py)。

- `ExecutionSlot(Serial.definition_id, hooks, instance_id="root")` 创建串行组件的插槽；Serial(ctx, slot) 要求插槽与自身定义匹配。
- `ExecutionPlug(definition_id, execute, instance_id="worker", states=...)` 暴露执行和地址；slot.connect(plug, priority=...) 返回两端地址与 schema 的握手信息。
- StateBinding(key, location=...) 在显式位置上加入 run_id，不自动加入 definition_id、instance_id 或 execution_id。需要实例隔离的业务地址由装配明确填写；同一运行中的重复调用可以更新同一地址。
- 控制状态使用 `org.aurora.control:state/control`，按 definition_id、instance_id、run_id、execution_id 定位，携带父调用及当前选择/迭代信息。
- 控制状态只覆盖在途调用。完成、失败、取消时先发布终态变化，再删除本次地址，不保存调用树或历史。需要记录过程的订阅者自行收集。
- 控制组件没有脱离根调用的后台任务；根调用可交给 Lifecycle.run 跟踪。业务状态保留策略由装配负责。

| 组件 | 执行语义 |
| --- | --- |
| Serial | priority 从小到大，同值按连接顺序，逐个等待；失败或取消停止后续调用 |
| Branch | 选择函数返回一个子实例 instance_id；None 跳过，未知实例报错 |
| While | 先判断条件，只连接一个循环体；多步骤用 Serial；显式正整数 max_iterations，达到上限且条件仍真时失败 |
| Parallel | 显式正整数 concurrency 控制异步并发；失败或取消时取消其余任务并等待清理，再传播异常 |

Controller 是公共基类定义，不是可独立运行的第五种控制流程。Parallel 不提供线程执行或共享 ctx 写入事务。

## 3. 模型协议与调用组件

### 3.1 aurora_adapter.model

源码：[models.py](../../../packages/aurora_adapter/src/aurora_adapter/model/models.py)、[protocols.py](../../../packages/aurora_adapter/src/aurora_adapter/model/protocols.py)、[fake.py](../../../packages/aurora_adapter/src/aurora_adapter/model/fake.py)。

- Message、ToolDefinition、ToolCall、ModelRequest、ModelResponse 与 ModelChunk 用 TypedDict 表达普通 JSON 数据，不包含 SDK 对象。
- ToolCall 包含完整 id、name、arguments；参数必须是完整 JSON 对象。供应商的参数片段由适配层组装，bot 不消费半截 JSON；文本仍逐段输出。
- await client.complete(request) 返回完整响应；async with client.stream(request) as chunks 消费异步片段。
- chunk 区分 text、tool_call、finish。ResponseBuffer 累计文本与完整工具请求，不保留片段历史，要求唯一且最后的 finish；缺失结束、重复工具 ID 等协议错误明确失败。
- finish_reason 为 stop、tool_calls、length、content_filter。模型响应结束不代表整个 bot 对话成功完成。
- ModelCapabilities 声明 streaming、tool_calls；能力不足明确拒绝，不自动降级。请求包含工具定义或工具历史时同样检查工具能力。
- ModelFactory 是异步工厂协议，接收 ModelConfig 与关键字 api_key。ModelConfig 提供 model、可选 base_url 与能力声明；凭证从运行期参数注入，不写入 ctx。工厂加载与绑定恢复已由 TOML profiles 和 `state/bindings` 实现。
- ModelError、UnsupportedCapability、ModelProtocolError 表达模型边界错误；取消和超时沿用标准异常，真实供应商错误映射待适配器实现。
- FakeModel 通过 FakeReply 回调确定性生成输出，无网络和密钥依赖，可用于完整响应、流式、工具请求及故障测试。它没有单独的公共 adapter ID。

插件入口为 aurora_adapter.model，登记模型适配器注册表、客户端服务、四个模型 schema 与两个模型配置状态。LiteLLM 与 `org.aurora.adapter:state/model/config`、`org.aurora.adapter:state/model/bindings` 已实现。

### 3.2 aurora_agent.model

源码：[model.py](../../../packages/aurora_agent/src/aurora_agent/model.py)。

`ModelCall(ctx, client, *, instance_id=None, request_state, output_state, streaming=True)` 使用注入客户端，从 request_state 读取请求，在 output_state 更新同一个 ModelCallState。插头通过 states 的 input/output 交换地址。

输出包含 status、execution_id、text、tool_calls、finish_reason，失败时包含异常类型名称 error。收到部分文本后失败或取消时保留文本，并标记 failed/cancelled；异常继续传播。completed 只表示这次模型请求完成，不执行工具或继续 ReAct。

调用组件通过上下文管理关闭单次响应流，装配在全部调用结束后关闭共享 client。同一输出地址必须串行调用；不同 run 可分开定位，但客户端是否支持并发仍由其实现决定。

插件入口为 aurora_agent.model，登记 ModelCall component 与其 /execute 两项定义。实际组件 ID 为 `org.aurora.agent:handlers/model_call`；ReActDefaults 将模型调用连接到 infer 阶段。

## 4. 宿主与存储边界

core 的关键接口与注意事项：

- Context、StateKey、install_context：状态地址由完整 ID 与业务定位构成；读写复制，set 整项替换，每次成功 set 均通知，list 返回已赋值地址并排序。缺失 get 抛 KeyError，缺失 delete 返回 False。
- ctx 访问限宿主线程；同线程单次修改有序，读改写不是事务。EventBus 同步分发后续事件，监听器异常不撤销已提交状态。
- ContextPersistence 默认保存全部 ctx，快照要求严格 JSON，后台合并写入；Context.set 只执行已配置校验，不保证值可序列化。运行时服务、连接、任务由装配持有，凭证不写入 ctx。
- StorageService 使用显式数据根，提供 framework/ctx.json、framework/structured.sqlite3 及插件命名空间目录；插件可自行管理数据库。
- Lifecycle 恢复快照后执行 configure，再 prepare/start。Lifecycle.run 跟踪根调用；组件自行创建的任务由其所有者收束。
- 关闭顺序为停止入口、等待/取消在途调用、组件最后写入、最终 flush、释放资源。停止或落盘失败报告错误并保留可重试资源，不假报正常退出。

五个示例各自使用独立数据目录。状态保留与裁剪由各示例明确，core 不提供自动裁剪。快照恢复不自动重建实例或续跑调用。

CLI 基础能力：

- 内置 commands/ 直接子包导出无参数 plugin()，自动发现；外部插件通过 aurora.plugins entry point 显式选择。
- main、commander、declarations、parsing、execution、host、presentation 分担入口、发现、声明、解析、执行、宿主和展示，不通过具体命令 ID 特判。
- 命令绑定 operation 或 executor 二选一；runtime 声明是否需要宿主。passthrough 只在显式启用时保留原始 argv，不拼接 shell 字符串。
- CLI 装配入口是同步工厂，关键字接收 registry、ctx、hooks、storage、workspace_root，返回 LifecycleComponent 可迭代对象；资源初始化在 prepare/start。workspace_root 来自宿主入口解析的 --root。这不冻结默认 bot 的装配格式。
- M2 交付时已有 about、check、donk、help、ctx get/set/delete/list/watch、run、id/list；随后增加 `run submit/activate/cancel`，没有常驻 chat 入口。id list 不启动宿主，不包含 prepare/start 动态登记的项。
- CLI 操作本进程宿主；另起进程不能凭共享数据目录取消在途任务。流式对话与取消须维持实际宿主关联，bot 不硬依赖 CLI/API 实现。

## 5. 接续任务与待定决策

M2 全部任务已完成，整体验收见 [变更记录](../../CHAGELOG.md) 的 M2.8 条目；当前 M3 的接续队列见 [计划第 11 节](plan.md)。

| 决策 | M2 已确定 | M2 后仍需处理 |
| --- | --- | --- |
| D03 绑定恢复 | ctx 保存 JSON，装配持有运行时对象，凭证单独注入；TOML profiles 与 `state/bindings` 重建客户端与实例 | 无 |
| D05 默认装配 | 定义、实例、运行、执行身份分离；端口显式连接；DefaultAssembly 提供默认根组件与注入 | 无 |
| D06 资源收尾 | 宿主根调用收束，单次流由调用方关闭，共享客户端与工具由装配关闭 | 真实 HTTP 客户端接入时复核取消与清理 |
| D07 真实模型边界 | 异步协议、完整工具请求、逐段文本、终态、能力拒绝、LiteLLM 映射与供应商错误 | 无 |
| D10 对话运行 | AgentRuntime 提供提交、激活、取消、忙碌与取消竞态处理；重启遗留 run 标记为 failed | 界面动作与运行的关联（M3.6） |
| 工具与 ReAct | 参数校验、失败与超时观察、观察回填、终止限制 | 无 |
| CLI 流式接入 | `run submit/activate/cancel`、增量输出、Ctrl+C 同宿主取消、bot 无 CLI 硬依赖 | 常驻 chat 入口与界面协议随 M3 决定 |

不默认写 ctx 就等于 send，不承诺事件可靠投递或重启透明续跑。规划中的 conversation 操作和端点不强制决定 TUI/Panel 的交互机制。

依赖方向为 core ← control ← agent ← bot；adapter 基础包仅依赖 core，模型配置通过 model extra 引入 config，供应商 SDK 通过 litellm extra 安装；模型协议被 agent 与 bot 使用。LiteLLM SDK 类型只停留在适配器内部。M3 的 HTTP/WS、client/TUI 和 M4 的多模型、agent、MCP 不在 M2 交付范围内。

## 6. 检查与证据

M2 验收与本次文档基线 `7b84b6b` 的完整 aurora check 通过：488 项 Python 测试、9 项工具链测试及格式、lint、类型检查。M2 中期曾在 `4eb4d6e` 报告 256 项测试；该数字仅作为当时的进度记录，不代表当前范围。

```powershell
uv sync --all-packages
pnpm install --frozen-lockfile
uv run aurora check
pnpm typecheck:python
uv run pytest packages/aurora_adapter/tests/contract/test_model_protocol.py packages/aurora_control/tests/unit/test_component_identity.py packages/aurora_control/tests/unit/test_control.py packages/aurora_agent/tests/unit/test_model_call.py tests/e2e/test_control_flow_example.py tests/e2e/test_react_defaults_example.py -q
uv run aurora --plugin aurora_control --plugin aurora_agent.model --plugin aurora_adapter.model id list
```

行为证据：

- [组件身份](../../../packages/aurora_control/tests/unit/test_component_identity.py)：定义层级、实例隔离与展示引用。
- [模型协议](../../../packages/aurora_adapter/tests/contract/test_model_protocol.py)：流关闭、能力拒绝、结束和工具请求。
- [控制组件](../../../packages/aurora_control/tests/unit/test_control.py)、[模型组件](../../../packages/aurora_agent/tests/unit/test_model_call.py)：组合、失败、取消、临时状态清理与部分文本。
- [控制示例](../../../tests/e2e/test_control_flow_example.py)、[独立 Agent 示例](../../../tests/e2e/test_react_defaults_example.py)：真实进程、退出码与最终快照。
- [宿主关闭](../../../tests/e2e/test_lifecycle_persistence.py)、[CLI 进程](../../../tests/e2e/test_cli.py)：在途写入、最终落盘和重启恢复。

检查范围与改动相称，真实模型冒烟与离线测试分别报告；没有实际连接时不宣称真实模型已验证。注释、docstring 和提交使用中文，提交以动词开头、小步交付；README.md、AGENTS.md 修改须先经用户确认，变更叙述集中在 docs/CHAGELOG.md。
