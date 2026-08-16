# AuroraBot 架构实施说明

本文是 [RFC 0300](docs/rfc/0300-unified-architecture-and-contracts.md) 的实施说明。RFC 0300 是唯一设计基准；本文用于帮助
开发者定位包、数据流、组合方式和改动入口，不记录历史架构。

## 1. 系统全景

AuroraBot 由一条 Agent 热路径和一条检查路径组成：

```text
外部事件 / Console / Panel
            │
            ▼
      contracts 输入端口
            │
            ▼
  engine: Inbox → Triage → Agent → Activity → 因果/终态
                    │            │
                    │            ├── ModelProvider → ai
                    │            ├── ToolExecutor  → memory / platform
                    │            └── MemoryStore   → memory
                    │
                    └── ops 查询端口 → Console / Panel / 导出

aurora 组合根创建并连接全部具体实现，管理启动、运行和关闭。
```

核心判断：

- engine 完整拥有状态和 pump，不认识具体 Provider、Memory、Agent 包或 Platform；
- Agent handler 是纯决策函数，不执行真实效果；
- ToolExecutor 承担所有环境效果，结果以 AMP 回到 engine；
- ops 和 Console 位于热路径外，只通过窄端口输入或查询；
- SQLite 是运行态、终态和恢复的唯一权威。

## 2. 依赖结构

```text
                    aurora
       ┌──────────────┼────────────────┐
       ▼              ▼                ▼
      ops           engine          platform
       │              │                │
       │          contracts/utils      │
       ▼                               ▼
contracts/utils   ai  memory  agents  prompt  config  console
```

实际约束以 `tests/test_dependency_boundaries.py` 为准：

- `engine → contracts + utils`；
- `platform → contracts + utils`；
- `ops → contracts + utils`；
- `agents → prompt + contracts + utils`；
- `src` 不导入 `aurora`；
- `sandbox` 只依赖 utils，且不参与当前运行时。

## 3. 包职责

### `src/contracts`

跨层 DTO、枚举与 Protocol 的唯一位置，主要包括：

- AMP、事件来源和输入；
- Task、Agent、消息、Activity 和决策；
- ModelRequest、ModelResult、continuation 和 ToolCall；
- ToolExecutor、MemoryStore、ModelProvider 和查询 Port；
- OperationSpec、ParameterSpec 和 OperationResult；
- 完整不可变配置快照。

contracts 不依赖任何上层实现。

### `src/engine`

AgentEngine 和 SQLiteRuntimeStore 组成完整热路径：

- `runtime.py`：pump、模型派发、记忆 hook、生命周期和查询门面；
- `ingress.py`：AMP 持久化与工具回执分流；
- `authorize.py`：权限检查与决策应用入口；
- `tool_registry.py`：能力目录、派发和恢复；
- `store/inbox.py`：Inbox、防抖、session revision、批次和 triage Task；
- `store/decisions.py`：generation 抢占、提交屏障、原子状态迁移、消息和 Activity；
- `store/runtime.py`：Task、Agent、事件、session lane 和已提交输出查询；
- `store/migration/`：Schema v10 历史版本迁移。

engine 的同步存储调用运行在单进程事件循环所有权模型中。模型、工具和 MemoryStore 是 async；MemoryService 将
SQLite、mem0、embedding 与语义检索等阻塞工作移出事件循环，handler 只接收已经固定的快照。

### `src/agents`

Agent 逻辑实现和模型可见主动能力：

- `TriageAgent`：批次的 process/defer/discard，并在 fast 快脑与 root 主脑之间选择获权委派目标；
- `ToolAgent`：模型请求、多 Tool call 可恢复链、委派和完成；
- `capabilities/delegate.py`：创建同构子 Agent；
- `capabilities/wait.py`：等待未终止 children；
- `capabilities/memory.py`：生成主动记忆 ToolRequest。

handler 只能读取 AgentContext 并返回 AgentDecision。

### `src.ai`

模型网关总分结构：

- `gateway.py`：Provider、模型绑定、能力协商和外部查询；
- `roles/`：fast、quality、multimodal、embedding 的自包含实现；
- `roles/base.py`：共享纯函数、ChatCaller 和响应解析；
- `models.py`：models.dev 能力、模态与价格缓存；
- `execution.py`：生成任务与费用统计；
- `cost_store.py`：费用 SQLite；
- `providers.py`：LiteLLM 与 OpenAI-compatible Provider 解析。

聊天角色统一使用 Chat Completions 形状；embedding 使用独立 endpoint。

### `src.memory`

同源记忆服务：

- `models.py`：纯 SQLAlchemy 数据声明，不包含服务或查询逻辑；
- `short_term.py`：窗口、异步概要、词项窗口检索和统一字符预算；
- `service.py`：异步 MemoryStore 编排、durable facts、查询门面和降级合并；
- `long_term.py`：mem0/Chroma 语义记忆适配；
- `executor.py`：主动记忆工具执行与 AMP 回执；
- `migration/`：memory SQLite 版本。

被动记忆和 memory Agent 写入同一数据源。MemoryContextSnapshot 在模型调用前固定；models 不依赖 service，短期算法不
感知 engine 或 ai 的具体实现。

### `src.platform`

当前只实现 MCP：

- `adapter.py`：本地/远程会话、工具发现、执行和通知归一化；
- `client_manager.py`：stdio MCP client 生命周期；
- `server_kit.py`：本地子进程管理；
- `server_spec.py`：启动描述。

MCP 工具变为 `aur.mcp.*` 能力，执行结果通过 AMP 回到 engine。

### `ops`

系统唯一后端和检查路径：

- `registry.py`：OperationSpec 自动注册和冲突校验；
- `parser.py`：文本参数解析；
- `router.py`：文本命令与 REST 路由同构；
- `operations/`：engine、memory、ai、config、messages 和 console 操作；
- `api.py`：Panel 认证、操作路由、附件、Lab 和输出 WebSocket；
- `store.py`：bootstrap token、session 和附件索引；
- `runtime.py`：组合各窄查询 Port。

ops 不参与 pump，也不直接导入具体实现包。

### `aurora`

唯一组合根：

1. 加载配置快照；
2. 创建 Prompt、Agent handler、ModelGateway 和 MemoryService；
3. 创建 AgentEngine 并注入 Port；
4. 创建选定 Platform 并绑定 ToolExecutor；
5. 创建 Panel 和可选 Console；
6. 运行共享停止信号；
7. 按有界顺序关闭后台任务、server、平台和存储。

## 4. 一条消息的生命周期

```text
submit_amp / submit_conversation
  → persist_amp
  → inbox_events(PENDING)
  → quiet/max-wait 到期
  → create_triage_task
  → triage model request
  → process/defer/discard
  → process: delegate fast or root
  → fast direct/tool response, or root/worker model request
  → text / tool / delegate / wait / complete
  → Activity dispatch
  → model.completed / tool.* / child.*
  → root terminal
  → triage terminal
  → Task terminal + causal_events + memory projection
```

### Inbox 与 Triage

同一 session 的连续事件聚合成一个有界批次。入口 Task 的 root Agent 是 triage；process 后按结构化结果创建不能委派的
fast 快脑或具备完整委派能力的 root 主脑。模型或结构化输出失败时 fail-open 到 root，保证输入不会静默消失，也不会把
不确定任务错误压入快速路径。

### 持续输入与有界抢占

持续 AMP 不直接重启每一次生成。`session_lanes` 以会话主键保存 observed、generation、committed 三个 revision、输入
watermark、活动 Task 与抢占预算；生成期间的新事件先进入 delta，同一会话最多一个交互 generation。只有直接点名、明确
纠正或使当前回复失效的事件可以请求抢占，且抢占次数与总等待有硬上界。普通群聊消息在当前回复提交后切入下一轮，避免
高流量会话让 Bot 永远无法插话。

旧 generation 被取代后只能保留审计记录，不得创建消息、工具效果或用户输出。模型、工具回执和输出发布都校验 Task、
session lane 与 generation revision；用户侧只读取 `output_publications` 单调提交流。不支持撤回的平台因此看不到旧结果。
PROCESSING 的不可撤回工具阻止抢占并先完成。模型和工具调度按空闲槽连续领取工作，跨 session 先公平分配，再填充余量。

### Agent turn

每轮只领取一条持久化消息：

1. 读取 Task、Agent、children、记忆和获权工具；
2. 构造不可变 AgentContext；
3. 调用 handler；
4. 校验能力、委派和 triage 控制权限；
5. 在单事务内应用 AgentDecision；
6. 派发新产生的 Activity。

### 多 Tool call

ToolAgent 将同一模型响应中的调用保存为可恢复链。每项调用都有真实 Tool result，链尾才恢复模型 continuation。进程崩溃
后，已持久化 Tool Activity 可以重新派发，重复回执由 request ID 幂等消费。

## 5. 状态与恢复

### Task

Task 从 triage 创建，持有 session、优先级、交互/自主标志和模型、工具、时长预算。终态包括完成、静默、失败、取消和预算
耗尽。终态行保留在 runtime SQLite。

### Agent

Agent 持久化 READY、RUNNING、COMPLETED、FAILED 等基态。等待模型、工具或 children 由 Activity 和监督树派生，不额外持久化
易漂移的等待状态。

### Activity

模型和工具请求先落库，再派发。启动恢复时：

- PROCESSING 消息回到 PENDING；
- 中断模型 Activity 结束并产生 model.failed；
- 工具 Activity 保留并由 ToolRegistry 恢复。

## 6. Prompt 与记忆

PromptDocument 最多由三层组成：

1. stable system：SOUL、WORLD、Agent profile；
2. optional memory system：概要、最近窗口、相关事实；
3. current user：批次、assignment、工具结果或 child report。

外部事实通过 JSON 数据边界编码。Tool schema 只放模型原生 tools 参数，不在正文重复。

记忆目标形态为：

```text
最近原文窗口 → 超限批量压缩 → 会话概要
稳定事实     → durable facts + mem0/Chroma 语义检索
```

整个 MemoryContextSnapshot 按概要、最新窗口、语义/关键词事实的顺序满足统一字符预算；语义组件不可用时降级到
durable facts，并通过 memory status 公开降级状态。

## 7. 操作与输出

OperationSpec 是 Console 命令和 Panel REST 的共同定义。路径、参数和 OperationResult envelope 保持同构。

主要资源：

```text
GET/POST /engine/*      状态、Task、Agent、事件、摄入、pump、shutdown
GET      /memory/*      历史、检索、统计
GET      /ai/*          费用、模型、角色
GET      /agents/*      profile
GET      /config/*      脱敏配置和 Prompt
GET/POST /messages      会话历史与输入
GET      /activities    输出流游标
```

Panel 仅绑定 loopback。`/healthz` 无认证，`/api/auth/login` 仅负责凭 bootstrap token 换取 session；其余页面、Lab、操作、
附件和 WebSocket 都必须校验 Bearer 或同源 HttpOnly session cookie，WebSocket 还校验 Origin。

Console 和 Panel 均消费 engine output stream，不维护第二份 Bot 输出。

## 8. 工作区

```text
data/
  engine/runtime.sqlite3
  ai/cost.sqlite3
  memory/memory.sqlite3
  memory/mem0-history.sqlite3
  memory/chroma/
  ops/panel.sqlite3
  ops/Token.txt
  ops/uploads/
  platform/mcp/apps/
```

所有 SQLite 使用 WAL 和 `schema_meta`。全新库直接创建当前形状；旧库通过连续迁移步骤升级。代码不读取旧版列，也不读取
历史 JSON、JSONL 或文件 Inbox。

## 9. 配置加载

加载顺序：核心 TOML → runtime profile 覆盖 → 路径解析与交叉校验 → 不可变 AuroraConfig。未知键、越界路径、重叠存储、
非法平台、无效 App 或未声明 Prompt 必须在启动前失败。

环境变量只提供 TOML 明确引用的密钥。stdio App 只继承 `apps.toml` 列出的变量。

## 10. 改动入口

| 改动            | 首要位置                      | 要求                                             |
| --------------- | ----------------------------- | ------------------------------------------------ |
| 新跨层 DTO/Port | `src/contracts`               | 先更新 RFC 0300，补边界与契约测试                |
| 新决策语义      | contracts + engine/store      | 先更新 RFC 0300，补原子性和恢复测试              |
| 新模型角色      | `src/ai/roles`                | 自包含 endpoint 与适配，补 gateway 测试          |
| 新主动能力      | `src/agents/capabilities`     | 只生成决策，真实效果由 ToolExecutor 执行         |
| 新 MCP App      | `apps.toml` 或 extensions     | 显式配置、环境白名单、稳定 package               |
| 新 Platform     | contracts + platform + aurora | 先更新 RFC 0300，不得让 platform 依赖 engine/ops |
| 新操作          | contracts/operation + ops     | REST/文本同构，保持窄 Port                       |
| 数据库变更      | 对应 models + migration       | 连续迁移、失败回滚、当前形状测试                 |

Python 注释和 docstring 只说明局部行为，不引用具体 RFC 编号或章节。
