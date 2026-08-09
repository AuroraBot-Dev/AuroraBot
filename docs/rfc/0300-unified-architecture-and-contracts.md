# 0300：AuroraBot 统一架构与公共契约

状态：已接受
日期：2026-08-09
取代：此前全部 02xx 设计文件

## 1. 文档地位

本文件是 AuroraBot 唯一的 RFC，也是模块边界、事件语义、配置、扩展、模型调用、持久化、进程组合与运维接口的
唯一设计基准。仓库不再按历史阶段保留多份现行 RFC；历史判断由 Git 记录保存，当前工作树只描述当前有效契约。

优先级固定为：

1. 本 RFC；
2. 当前公共 contracts 与测试；
3. `ARCHITECTURE.md`、`docs/TECHNICAL.md`、README、配置样例和代码注释。

影响模块边界、事件、结构配置、扩展协议、模型调用、持久化语义或进程组合的改动，必须先更新本文件。除非先修改
本节的治理规则，仓库不得新增并行编号 RFC。

### 1.1 代码引用规则

- Python 源码和测试的注释、模块 docstring、类 docstring 与函数 docstring 不得引用具体 RFC 编号或章节。
- 代码注释只解释局部不变量、行为原因、数据形状和安全边界，不承担设计文档索引职责。
- 设计来源只在 `docs/rfc/`、`ARCHITECTURE.md`、`docs/TECHNICAL.md` 和 `ROADMAP.md` 中维护。
- 配置注释应描述字段语义，不以 RFC 编号代替说明。

## 2. 目标与原则

AuroraBot 是以因果事件、同构 Agent 和主动节律为核心的自主智能体框架。设计遵循以下原则：

- **Agent 中心**：模型理解并决定认知动作，engine 只保证状态、授权、预算、幂等与真实效果边界。
- **事件平权**：用户消息、应用事件、时间变化、工具回执和子 Agent 报告经统一事件语义进入认知流程。
- **判断与效果分离**：普通模型文本不能直接改变环境；外部效果必须经声明的能力、授权和 ToolExecutor 执行。
- **全同构**：triage、root、worker、memory 等 Agent 均由上下文、权限域和逻辑类三元组实例化。
- **单一热路径**：事件、Task/Agent 状态、邮箱、Activity、模型/工具调度和因果记录全部由 engine 拥有。
- **有界运行**：上下文、批次、并发、调用次数、持续时间、委派深度、队列和持久化增长必须有明确上界或治理入口。
- **可恢复与可审计**：所有外部效果和状态迁移都经过持久化 Activity 与因果事件，支持幂等和崩溃恢复。
- **当前契约优先**：不保留旧架构的隐式兼容读写；数据演进通过显式迁移完成。

## 3. 包边界与依赖方向

| 包              | 职责                                           | 可依赖                   |
| --------------- | ---------------------------------------------- | ------------------------ |
| `src/contracts` | 跨层不可变 DTO、枚举与 Port Protocol           | 标准库                   |
| `src/utils`     | 无业务状态的通用工具                           | 标准库                   |
| `src/config`    | TOML 加载、校验与不可变配置快照                | contracts                |
| `src/prompt`    | Prompt 目录、分层 DTO 与模型上下文装配         | contracts                |
| `src/engine`    | 完整 Agent 热路径、状态机、因果与运行态存储    | contracts、utils         |
| `src.ai`        | 模型角色、Provider、网关、能力缓存与费用统计   | contracts、utils         |
| `src.memory`    | 自动记忆服务、主动记忆执行器与持久化           | contracts、utils         |
| `src.agents`    | 只读上下文到决策的 handler 与主动能力          | prompt、contracts、utils |
| `src.platform`  | 外部生态输入和效果适配器                       | contracts、utils         |
| `src.console`   | 本地交互 Shell 与只读输出渲染                  | contracts、utils         |
| `ops`           | 热路径外的操作、查询、认证、面板与调试 sidecar | contracts、utils         |
| `aurora`        | 唯一进程组合根与生命周期所有者                 | 所有下层包               |

`src.sandbox` 保持孤立，只依赖 utils，当前 Agent 运行时不启用。

强制边界：

- engine 不导入 ai、memory、agents、prompt、config、platform、console、ops 或 aurora。
- Agent handler 只能读取 `AgentContext` 并返回 `AgentDecision`，不得直接写运行态、调用 Provider 或平台 Client。
- platform 不导入 engine 或 ops；输入和回执通过 contracts Port 注入。
- ops 不被 engine、platform 或其他热路径实现依赖。
- `src` 不导入 `aurora`。
- 跨层 DTO 和 Protocol 只定义在 contracts。
- 一个进程只有一个 engine 所有者。

## 4. 配置与组合根

### 4.1 配置文件

结构配置只使用 TOML，并按包级职责拆分为：

- `runtime.toml`：进程 profile、Console 与 Panel；
- `engine.toml`：Agent、triage、自主节律与 Task 预算；
- `models.toml`：Provider 和角色到模型的绑定；
- `platforms.toml`：平台偏好；
- `agents.toml`：Agent profile、权限域和委派范围；
- `apps.toml`：MCP 应用连接与启动描述；
- `prompts.toml`：Prompt 文件映射；
- `logging.toml`：日志级别与路径；
- `storage.toml`：包级持久化路径。

未知键必须在启动前失败。profile 只能覆盖 runtime；结构和启用状态不能由环境变量任意覆盖。密钥只从 TOML 显式
命名的环境变量读取，`.env` 仅用于本地开发注入。

### 4.2 进程组合

`aurora` 创建具体 Provider、MemoryStore、Agent handler、ToolExecutor、Platform 和 ops，并通过 contracts Port 注入。
配置在启动时加载一次形成不可变快照，变更通过重启生效。

`uv run aurora start` 使用平台 preference；重复的 `--platform` 构成精确平台集合。`--headless` 只禁用本地
Console，不改变平台集合。裸 `aurora` 只展示用法。

平台和面板使用强类型生命周期句柄。启动失败必须回收已经创建的资源；关闭顺序由组合根统一协调，后台任务异常必须
传播到进程所有者，不能静默丢失。

## 5. AMP、摄入与因果语义

AMP 是外部事实和工具回执的统一信封。外部摄入只允许通过 `submit_amp` 或 `submit_conversation` 进入 engine，直接写入
SQLite；不存在文件投递箱、inbox/archive 目录、JSON 归档或 JSONL 会话日志。

生产者必须提供稳定的消息标识。engine 以消息标识和因果记录保证幂等，重复输入不能创建重复工作。工具回执使用保留
事件类型，必须匹配已经持久化的 Activity；它们不进入普通 Inbox。

平台或应用可以在生成 AMP 前按显式 TOML 规则过滤无持续语义的供应商瞬时事件。过滤只能发生在外部归一化边界，不能
改写已经进入 engine 的事实。Aurora-QQ 默认过滤输入状态类瞬时通知。

`causal_events` 是会话可读性、调试和导出的权威来源。ops 可按需导出投影，热路径不写会话日志文件。

## 6. Inbox、Triage 与 Task 准入

外部语义事件遵循唯一流程：

`AMP → 持久化 Inbox → 会话防抖批次 → triage Agent → root Agent → 决策/效果 → 终态 → 记忆投影`

- Inbox 按 `session_id` 分区；新事件刷新 quiet window，但不得超过首条事件的 max wait。
- 批次同时受事件条数和字符预算约束，超大事件必须在进入模型上下文前形成有界投影。
- 每个到期批次创建一个 Task 和一个入口 triage Agent；Task 从 triage 开始，不存在旁路准入策略。
- triage 无工具，只能 `process`、`defer` 或 `discard`。
- `process` 必须同时选择一条获权认知路径，并通过普通委派携带批次的有界事实投影：清晰、低风险、可在短链路内完成的
  事件交给绑定 fast role 且可以调用工具的 `builtin.fast`；复杂、含歧义、高影响、需要规划或可能委派的事件交给
  `builtin.root`。不确定、字段缺失、非法目标及 fail-open 一律选择 `builtin.root`。
- triage 只能在自身 `child_profiles` 中选择目标。`builtin.fast` 不得继续委派，避免快速路径退化为无界代理树；
  `builtin.root` 保持现有 worker 与 memory 委派能力。
- `defer` 必须给出下一次时间且受总 defer 上界约束；`discard` 删除原始 Inbox 数据。
- 模型失败或结构化输出失败时 fail-open 为 `process`，不能静默丢失用户输入。
- triage 可产生稳定事实候选，随因果记录进入终态记忆投影。

## 7. Agent 同构、状态与决策

Agent 实例由三元组定义：

1. `AgentContext`：当前 Task、Agent、消息、children、记忆快照和获权能力的不可变视图；
2. `AgentProfile`：逻辑实现、模型角色、能力权限域、委派授权与资源边界；
3. `BaseAgent` 子类：纯 handler，实现 `AgentContext → AgentDecision`。

内建角色为 triage、fast、root、worker 和 memory。triage 在 fast 快脑与 root 主脑之间选择；fast 使用低延迟模型直接
响应或调用工具且不能委派；root 是完整本体意识入口；worker 处理委派工作；memory 是只获主动记忆能力的专精 Agent。
委派是创建子 Agent 的唯一方式，形成有界监督树。

一次 `AgentDecision` 是一个原子状态迁移，只允许以下互斥主分支：模型请求、工具请求、委派、完成、等待、defer、
discard 或失败。等待不是持久化状态，而由未终止 children、待处理报告和活跃 Activity 派生。

状态、消息、Activity、因果事件与相关计数必须在同一数据库事务中更新。handler 异常必须转为可审计失败，不能留下
已领取但不可恢复的消息。

## 8. 认知自由、授权与预算

- Prompt 负责人格、表达习惯和交互约定；模型决定本轮文本和全部 Tool call。
- 运行时不得截断、伪造拒绝、改写空文本或只执行第一个 Tool call。
- Provider 返回的多个 Tool call 必须全部恰好一次进入可恢复执行，并在同一 continuation 中获得对应结果。
- 控制能力和外部效果能力可以出现在同一模型响应中。
- `parallel_tool_calls` 由请求和 Provider 能力协商决定，网关不得全局关闭。
- engine 只约束真实效果：能力存在、Agent 获权、参数符合 schema、回执匹配请求且预算未耗尽。
- 能力授权支持精确 ID、前缀通配、全通配和 `!` 排除，排除优先。
- 模型调用数、工具调用数、Task 时长、并发数、上下文字符数、委派深度、总 Agent 数和子 Agent 数都是硬资源边界。
- 新外部输入只唤醒对应工作，不自动取消正在运行的自主 Task。交互 Task 的抢占遵循下一节的会话 revision 规则。

## 9. engine 运行与恢复

engine 使用单进程 asyncio 独占模型：无数据库租约、无乐观锁、无多 owner 协调。一次 pump 按顺序执行：

1. 领取无活动 generation 的到期 Inbox 批次并创建 triage Task；
2. 领取 Agent 消息，通过异步 MemoryStore 取得有界快照、构造上下文、调用 handler、授权并原子应用决策；
3. 唤醒模型与工具后台派发器；空闲槽立即领取下一项，不等待同批其余工作；
4. 对终态交互 Task 进行异步记忆投影；
5. 更新可查询输出和因果投影。

持续输入场景采用会话级有界抢占，而不是每条 AMP 都重启生成：

- `session_lanes` 以 session 主键持久化 `observed_revision`、本轮冻结 `generation_revision`、已发布
  `committed_revision`、`generation_watermark` 与唯一 `active_task_id`；生成期间到达的新事件进入 watermark 之后的 delta，
  不隐式改写已经冻结的上下文，同一 session 不能并行存在两个交互 generation。
- 普通环境消息只进入 delta。直接点名、直接回复、明确纠正或使当前回复失效的高优先级事件才可以请求抢占；每次回复的
  抢占次数和总等待时间必须有硬上界，达到边界后必须完成、静默或放弃，不能形成持续重启活锁。
- 抢占使旧模型 Activity 进入 `SUPERSEDED` 终态，并向 asyncio 与 Provider 流传播取消。晚到模型结果和工具回执必须再次校验
  Task、session lane 与 generation revision，不得恢复 Agent、创建后续工具效果或进入用户可见输出。
- 普通 delta 不使已经冻结的回复失效，因此当前 generation 可以先提交并在下一轮消费 delta。接受的抢占会原子撤销旧
  generation 的提交资格。用户输出只能先写入 `output_publications` 提交流，再由平台读取；不支持撤回的平台只接收该流中的
  最终输出。已经进入 PROCESSING 的不可撤回工具效果不抢占，先完成效果，再在下一轮消费 delta。
- 到达 quiet/max-wait 边界后冻结本轮 watermark，后续低优先级事件进入下一轮。调度按 session 公平分配，并使直接交互
  高于自主与后台工作，保证持续大流量群聊中既能插话又不会独占全部并发。

模型和工具派发不得使用整批完成屏障；任一并发槽释放后应立即按优先级领取下一项工作。工具效果默认不可抢占，只有能力
契约明确支持取消且尚未越过提交屏障时才允许取消。

启动恢复规则：PROCESSING 消息回到 PENDING；中断的模型 Activity 结束为 ERROR 并投递失败消息；工具 Activity 保留并
由 ToolRegistry 后台恢复派发。恢复不得重复产生真实外部效果。

MemoryStore 是异步 Port。SQLite 操作、概要模型调用、embedding 与语义检索不得作为同步网络或阻塞 I/O 运行在 engine
事件循环中；实现应使用原生异步接口或受控工作线程。handler 只接收已经固定的记忆快照，不感知异步实现。

## 10. 工具与能力

能力 ID 使用稳定的 `aur.*` 域：

- MCP 外部能力：`aur.mcp.<package>.<method>`；
- 内建服务：`aur.serv.<service>.<method>`；
- Agent 主动能力：`aur.agent.<method>`。

所有执行效果实现统一的 `ToolExecutor`，由组合根收集为扁平绑定目录并注入 engine。工具参数只来自能力公开 schema；
运行时不能向任意外部 schema 注入隐藏参数。只有能力显式声明 `runtime_completion` 时，才允许公开完成 Task 的参数。

工具结果统一构造 `tool.succeeded`、`tool.failed` 或 `tool.rejected` AMP 回执，包含请求标识、状态、规范化结果或错误。
成功结果只保留一种规范表示：优先结构化内容，其次可解析 JSON 文本，最后纯文本。

## 11. 模型网关

`src.ai` 提供总分结构：gateway 负责 Provider、角色绑定、能力协商、任务与费用；`roles/` 中每个角色自包含 endpoint、
能力基线、请求适配和响应解析，公共逻辑只以纯函数复用。

预设角色：

- `fast`：低延迟 triage 和短决策；
- `quality`：复杂推理；
- `multimodal`：多模态输入；
- `embedding`：词嵌入。

聊天角色统一使用 Chat Completions 语义；embedding 使用 embeddings endpoint。`models.toml` 只绑定 Provider 和 model，
endpoint 与角色语义归代码。模型能力以 models.dev 为主要信息源，TOML 显式能力为高优覆盖；冷启动缓存不可用时采用有界
等待和可审计降级，不能无限阻塞。

对外接口包括 `complete`、`get_response`、模态查询、费用统计、同步 embedding 和 OpenAI 兼容 client 导出。费用记录落
`data/ai/cost.sqlite3`，必须支持版本化迁移和有界查询，不得把无界历史作为长期启动前提。

## 12. 记忆引擎

记忆由一个 `MemoryStore` 同源承载，被动终态投影和主动 memory Agent 写入同一存储。模型调用前取得不可变快照，handler
不能直接访问记忆实现。

memory 包内部保持三类职责分离：`models.py` 只声明持久化数据形状，`short_term.py` 负责窗口、概要与预算算法，
`long_term.py` 负责语义适配，`service.py` 只编排异步 Port、durable facts 与降级策略。数据模型不得反向依赖 service。

记忆分三层，其中窗口与概要是按会话隔离的「域内层」，长期事实是跨会话共享的「全局层」：

1. **窗口**：按 `session_id` 隔离的最近原始 user/assistant 消息，保持域内上下文连贯；
2. **概要**：窗口溢出后批量压缩较旧消息，反复压缩最早内容形成自然遗忘；同样按 `session_id` 隔离；
3. **长期事实**：统一写入 `scope="global"` 的稳定事实，跨会话共享，保留来源（`source_task_id`）与去重语义，
   优先使用语义检索，失败时降级为关键词检索。

除本域快照外，recall 还必须附带「跨域动态」：时间阈值（`remote_recency_seconds`，默认 6 小时）内有更新的其他会话域，
取其概要（按最近更新倒序）与最近尾部消息（每域 `remote_tail` 条，默认 20，跨域合并后按时间正序）；超过阈值的域视为
非活跃，不进入快照。跨域动态渲染必须携带域标签（如 `qq:group:xxx`），使模型明确消息来源域。

窗口使用上下界，超过上界时一次压缩回下界。概要通过异步 MemoryStore 调用 fast 角色生成；模型不可用时允许规则降级，
但降级必须可观察。长期语义检索通过组合根注入配置的 embedding 角色，并使用配置的聊天角色驱动 mem0/Chroma；不得在
memory 包内硬编码 Provider、模型或密钥。语义检索无结果或失败时，必须确定性回退到 durable facts 关键词排序。

`MemoryQuery` 必须同时约束条数和整个快照的字符预算。summary、window、跨域概要、跨域尾部与 relevant facts 合计
不能超过预算；选择顺序和裁剪固定为本域概要、从新到旧选择的本域窗口、跨域概要（按活跃度倒序）、从新到旧选择的
跨域尾部、语义/关键词事实；窗口与跨域尾部输出恢复时间正序；任一单项可在剩余预算内裁剪。本域窗口最多消费
剩余预算的 2/3——跨域动态与相关事实合计至少保留 1/3（上限 8000 字符）的保障预算，防止本域原文占满预算后
跨域动态不可见。Prompt 只渲染有界记忆，不回放完整因果历史，也不重复渲染原生 tools schema。

## 13. Platform、MCP 与应用

Platform 将外部生态归一化为 AMP，并执行获权效果。当前平台注册表只包含 MCP；Console 和 Panel 不是 Platform。

MCP 支持本地 stdio 和 HTTPS Streamable HTTP：

- 本地子进程只继承基础安全环境和 `apps.toml` 显式允许的环境变量；
- 远程连接的认证变量必须显式声明；
- 启动前验证工作目录、命令、URL 和必需环境变量，错误必须指出具体 App；
- 动态发现工具并生成稳定、可读、可碰撞处理的能力 ID；
- 通知队列有界，背压不能静默丢失持续语义事件；
- 连接意外断开必须传播到组合根；关闭按会话、任务和子进程顺序有界完成。

内建 App 由 MCP 运行，私有数据落 `data/platform/mcp/apps`。主动节律由 Clock App 产生持久化心跳事件，并受 engine 的自主
Task 预算约束。

## 14. Console、ops 与 Panel

Console 是本地交互和渲染器，位于热路径外；它通过统一输入端口提交对话或操作，通过 output stream 渲染模型文本和
错误，不是外部效果能力。

ops 是唯一后端路由和检查 sidecar。RESTful 资源树是操作语义的唯一真源，斜杠命令是同一 OperationSpec 的文本形式；
两者共享参数模型、handler 和 `OperationResult` envelope。

操作域覆盖 engine、memory、ai、agents、config、prompt、messages、activities 和 console 控制。ops 只持有窄查询与输入
Port，不直接导入具体实现包。

Panel 是 ops 的 Web 形态，提供单一 FastAPI 应用：

- `/healthz` 是唯一公开业务信息的无认证端点；`/api/auth/login` 仅作为 bootstrap token 换取 session 的认证入口；
- 登录使用 `data/ops/Token.txt` bootstrap token 签发 Bearer session，并可设置同源 HttpOnly session cookie；
- 其余 HTTP、附件、Lab 和 WebSocket 端点全部要求有效 session；
- WebSocket 同时校验 Origin 白名单；
- Panel 只允许绑定 loopback；
- Console 和 Panel 输出同源于 engine output stream；
- 聊天历史来自 causal events 投影，不维护独立聊天数据库；
- 附件文件和索引属于 ops，消息中只传递稳定引用。

## 15. 持久化与迁移

持久化路径镜像包层级：

```text
src/engine           → data/engine/runtime.sqlite3
src/ai               → data/ai/cost.sqlite3
src/memory           → data/memory/memory.sqlite3 + data/memory/mem0-history.sqlite3 + data/memory/chroma/
ops                  → data/ops/panel.sqlite3 + Token.txt + uploads/
src/platform/mcp     → data/platform/mcp/
src/apps via MCP     → data/platform/mcp/apps/
```

SQLite 统一使用 WAL、busy timeout 和版本表。engine 当前 Schema 为 v10；ai、memory、ops 各自维护独立版本。v10 增加
`session_lanes`、Inbox/Activity generation revision 与只追加的 `output_publications`，v9 数据库通过 `v9_v10` 连续迁移。
实现使用
SQLAlchemy 2.0 ORM；原始 sqlite3 连接只作为迁移、诊断或测试逃生口，不进入热路径业务操作。

所有数据库演进必须提供 `vN_vN+1` 迁移步骤并提升目标版本。全新库直接创建当前 schema；旧库按连续版本序列在单事务
中迁移；缺失步骤、迁移失败或数据库版本高于代码都必须拒绝启动。代码路径只访问当前版本形状。

终态 Task 与详细因果事件保留在 engine SQLite。长期运行必须提供由 ops 触发的显式 TTL、导出、checkpoint 和清理机制；
不能在热路径中隐式归档或删除。外部消息幂等语义在清理后仍须保留必要墓碑或等价保证。

## 16. Prompt 与上下文

一次新模型调用最多包含：稳定 system、可选 memory system 和当前 user 事实。子 Agent 只接收 assignment、相关记忆和自身
结果，不继承 root 的完整历史。当前 Task、当前 Agent、全局 Agent 列表和工具 schema 不得重复注入。

外部事实必须以明确数据边界和规范 JSON 编码进入 Prompt，避免把数据解释为系统指令。SOUL、WORLD 和 Agent profile 是
配置化人格，不是授权边界。

## 17. 质量、安全与演化

- Python 3.12 为推荐版本；使用 uv 管理依赖。
- Ruff 行宽 120、LF、双引号；公开 API 提供类型注解，dataclass 优先 `slots=True`。
- `uv run aurora check` 必须覆盖 `aurora/`、`ops/`、`src/` 和 `tests/` 的 lint、format、类型和测试。
- 架构边界由 AST 导入测试保护；关键状态迁移、迁移、认证、恢复和幂等必须有回归测试。
- 主源码文件原则上不超过 500 行；超过时必须审查职责并优先按领域拆分。
- 日志使用 `src.utils.logging.get_logger()`；不得记录密钥、完整 Prompt、真实对话、continuation 或敏感工具载荷。
- Panel 不是公网多租户边界；当前保证是 loopback、单 owner、token 认证。
- sandbox 在启用前必须单独完成威胁模型、效果授权、资源限制和因果回执设计。

## 18. 验收基准

符合本架构至少要求：

1. 单一组合根和单一 engine owner；
2. 包依赖测试无违规；
3. AMP、Task、Activity 和 Tool receipt 的幂等及恢复测试通过；
4. Agent handler 保持纯决策边界；
5. 模型上下文、批次、队列和预算具有硬上界；
6. 数据库迁移可从支持的历史版本连续升级并可回滚失败事务；
7. Panel 认证、Origin、附件和 WebSocket 测试完整；
8. Console、Panel 与会话导出对同一因果和输出源保持一致；
9. 长期记忆的语义召回、降级和字符预算可端到端验证；
10. 干净克隆可以按默认文档完成可预测启动，未安装的外部扩展不会成为隐式必需项。
