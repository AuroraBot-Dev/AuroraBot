# AuroraBot 技术说明

本文描述 `nightly` 分支 0.5 alpha 的现行实现，帮助开发者定位包、数据流、状态、存储和扩展入口。唯一设计基准是
[RFC 0300](docs/rfc/0300-unified-architecture-and-contracts.md)；若本文、README 或代码注释与其冲突，以 RFC、跨层契约与测试为准。

## 1. 运行时全景

AuroraBot 以 Agent 为中心，但 Agent 不拥有进程、Provider 或 Platform。完整闭环是：

```text
Console / Panel / MCP notification
              │
              ▼
          AMP ingress
              │
              ▼
Inbox → Triage → fast/root Agent → model/tool/child Activity
  ▲                                      │
  └──────── tool receipt / child result ─┘
              │
              ▼
generation commit → output publication → memory projection
```

核心性质：

- 输入首先是环境事件；同一 `session_id` 的事件经过 quiet/max-wait 窗口聚合。
- triage 是同构 Agent，负责 `process`、`defer`、`discard`，并在 `builtin.fast` 与 `builtin.root` 之间选择。
- handler 只读取不可变 `AgentContext` 并返回 `AgentDecision`，不直接调用模型、数据库或外部客户端。
- 模型和工具请求先持久化为 Activity，再由后台并发槽派发；工具结果以 `tool.*` AMP 回到 engine。
- Task、Agent、消息、Activity、session lane、因果事件与用户输出均以 SQLite 为权威。
- ops、Console 与 Panel 在热路径外，通过契约 Port 输入或查询。

## 2. 包与依赖边界

```text
aurora                  组合根：配置、注入、启动、关闭
├── src/config          严格 TOML → 不可变配置快照
├── src/prompt          PromptDocument 装配
├── src/ai              模型角色、Provider、费用与模型查询
├── src/memory          短期/长期记忆与记忆 ToolExecutor
├── src/platform        MCP 工具、通知和生命周期适配
├── src/agents          同构 handler 与模型可见的主动能力
├── src/engine          唯一 Agent 热路径与运行时存储
├── ops                 操作树、Panel 后端、认证与附件索引
└── src/console         本地交互与只读输出渲染

src/contracts           跨层 DTO、枚举与 Port
src/utils               无业务语义的通用工具
src/sandbox             未启用的独立组件
```

`tests/test_dependency_boundaries.py` 执行以下约束：

- `engine → contracts + utils`；
- `platform → contracts + utils`；
- `ops → contracts + utils`；
- `agents → prompt + contracts + utils`；
- `src` 不导入 `aurora`；
- `sandbox` 只依赖 `utils`，也不参与当前组合根。

`aurora` 是唯一认识所有具体包的层。具体 ModelProvider、MemoryStore、AgentHandler 和 ToolExecutor 均由构造参数或绑定注入。

## 3. 核心数据流

### 3.1 摄入与 Triage

`submit_amp()` 先按 `message_id` 幂等落库。普通事件进入 `inbox_events`；工具回执不进入 Inbox，而是按 `request_id`
直接匹配原 Activity。同会话事件刷新 quiet 窗口，但不会超过 max wait。到期批次成为一个入口 Task：

```text
inbox_events(PENDING)
  → claim_triage_batches
  → Task(ACTIVE) + builtin.triage + task.started
  → process: delegate builtin.fast 或 builtin.root
  → defer: 批次回到延迟队列
  → discard: 删除批次，不产生用户输出
```

批次有事件数与字符预算；单条超大摘要会被确定性截断。Triage 模型或结构化输出失败时 fail-open 到 root，避免静默丢失输入。

### 3.2 Agent turn 与决策

每个 turn 原子领取一条 `PENDING` 消息并构造上下文：Task、Agent、children、记忆快照，以及 profile 授权后的 Tool 定义。
handler 返回且仅返回一种 transition：

| transition      | 结果                                                                 |
| --------------- | -------------------------------------------------------------------- |
| `model_request` | 创建 model Activity                                                   |
| `tool_request`  | 授权、schema 校验后创建 tool Activity                                 |
| `delegations`   | 创建获权的 child Agent 与 `agent.assigned` 消息                       |
| `completion`    | 完成 Agent；根完成时推进 Task 终态                                    |
| `wait`          | 等待语义由未终止 children 或待处理 child report 派生                  |
| `defer`         | 仅 triage 可用，延迟当前批次                                          |
| `discard`       | 仅 triage 可用，丢弃当前批次                                          |
| `failure`       | Agent 失败；根失败时 Task 进入 `ERROR`                                |

角色、工具、委派目标、深度、数量、Task 预算和 `triage_control` 均在应用决策前校验。决策、消息、Activity 与因果事件在单个存储事务中提交。

### 3.3 模型与工具 Activity

模型和工具 dispatcher 不等待整批慢任务结束：空闲槽出现后持续领取，先做跨 session 公平分配，再填充余量。

| 类型 | 请求路径 | 完成路径 |
| ---- | -------- | -------- |
| 模型 | `ModelRequest` → model Activity | Provider `complete()` → `model.completed` 或 `model.failed` |
| 工具 | `ToolRequest` → ToolRegistry → ToolExecutor | executor 提交 `tool.succeeded`、`tool.failed` 或 `tool.unknown` AMP |

ToolAgent 会持久化同一次模型响应中的多个 Tool call，并按序恢复。每项调用都有真实 Tool result；链尾才恢复模型 continuation。
重复工具回执按 `request_id` 幂等消费。`complete_task=true` 的成功工具可在存储层直接完成 Agent。

### 3.4 持续输入与 generation 提交

`session_lanes` 保存 observed、generation、committed revision、watermark、活动交互 Task 与抢占预算。同一会话最多一个交互
generation；生成期间的新事件先进入 delta。

- 普通新事件不重启当前生成，在当前结果提交后进入下一轮。
- 直接点名、明确纠正或使当前回复失效的事件可申请有界抢占。
- 抢占次数和 generation 总等待有硬上界；不可撤回且正在执行的工具会阻止抢占。
- 被取代 generation 的模型结果、工具回执和用户输出会被提交屏障拒绝，只保留审计事实。
- Console、Panel 与外部平台只消费 `output_publications` 单调提交流。

## 4. Agent 与 Prompt

### 4.1 Profile

`config/agents.toml` 中每个 profile 由三部分组成：

1. `implementation`：handler 类；
2. `model_role`：使用的模型角色；
3. `capabilities`：可见和可执行的能力范围。

委派另外受 `can_delegate` 与 `child_profiles` 约束。现行 profile：

| ID               | 职责                                | 委派范围                         |
| ---------------- | ----------------------------------- | -------------------------------- |
| `builtin.triage` | 注意力初筛                          | `builtin.fast` / `builtin.root`  |
| `builtin.fast`   | 低延迟直接回应或调用工具            | 无                               |
| `builtin.root`   | 本体意识与复杂任务规划              | worker / memory                  |
| `builtin.worker` | 执行具体子任务                      | worker                           |
| `builtin.memory` | 唯一获权主动写入长期事实的 Agent    | 无                               |

### 4.2 PromptDocument

一次模型调用至多包含三层：

1. stable system：SOUL、WORLD、Agent profile；
2. optional memory system：会话概要、最近窗口、相关长期事实；
3. current user：批次、assignment、工具回执或 child report。

外部事实以 JSON 数据边界编码；Tool schema 走模型原生 tools 参数，不在正文重复。continuation 属于模型协议状态，不写入人格提示词。

## 5. 模型网关

`src/ai` 按角色组织实现：

- `fast`：注意力初筛和短决策；
- `quality`：复杂推理与主工作流；
- `multimodal`：为后续多模态输入保留的角色；
- `embedding`：记忆语义检索。

模型与 Provider 绑定在 `config/models.toml`。模型能力优先从 models.dev 派生，TOML 的 `capabilities` 可显式覆盖；密钥只通过
Provider 声明的环境变量注入。当前 chat 角色统一使用 Chat Completions 形状，embedding 使用独立 endpoint。

网关同时负责：

- 工具定义与结构化输出能力协商；
- 流式收集、continuation 与取消传播；
- `models.dev` 能力/价格缓存；
- `data/ai/cost.sqlite3` 中的调用费用记录；
- 面向 ops 的角色、模型、费用和健康查询。

完整附件多模态链路尚未接通：Panel 可以保存附件并把引用送入输入数据，但运行时还未完成 MIME 解析、内容读取和 multimodal role 调用。

## 6. 记忆系统

`MemoryService` 组合三类数据：

```text
最近原文 window ──超限批量压缩──▶ session summary
终态投影 / Memory Agent ────────▶ global durable facts
durable facts ──embedding────────▶ mem0 + Chroma semantic memory
```

- `short_term.py` 管理最近窗口、异步概要、关键词候选和统一字符预算。
- `service.py` 编排终态投影、主动记忆、查询与降级合并。
- `long_term.py` 适配 mem0/Chroma；embedding 与 quality 模型由组合根注入。
- `executor.py` 执行 `aur.serv.memory.remember` 并通过 AMP 返回回执。

语义检索优先，随后合并窗口与 durable facts 关键词候选。mem0、Chroma、embedding 或语义查询不可用时，仍能回退到
durable facts 关键词检索；降级原因通过 `/memory/status` 查询。概要、窗口与相关事实共同服从 `MemoryQuery.max_characters`。

## 7. MCP 与能力授权

当前唯一 Platform 实现是 MCP，支持：

- 本地 stdio Server；
- HTTPS Streamable HTTP Server；
- `tools/list` 动态发现与 JSON Schema 参数校验；
- MCP notification 到 AMP 的归一化摄入。

MCP Tool ID 为 `aur.mcp.<app-package>.<raw-tool-name>`。Agent profile 的能力策略支持精确 ID、前缀通配、`*`，以及优先级更高的
`!` 排除规则。例如：

```toml
capabilities = ["aur.mcp.org.aurora.clock.*", "!aur.mcp.org.aurora.clock.delete_task"]
```

授权链是：`catalog ∩ profile.capabilities → descriptor 存在性 → JSON Schema → ToolExecutor`。模型普通文本不产生外部效果。

MCP 当前只把 tools 与 notifications 接入 Agent 上下文；resources 与 prompts 尚未接通。HTTP 会话或 stdio 子进程断开会结束当前
连接/进程，尚无稳定的自动重连与长期故障恢复保证。

内建 Clock App 默认关闭。启用后提供时间、持久化定时任务和自主 heartbeat；外部输入到来时由 engine 的交互优先级接管。

## 8. 操作树、Console 与 Panel

`OperationSpec` 同时定义 REST 资源和斜杠命令；二者使用相同参数规范与 `OperationResult` envelope。常用入口：

| 文本命令/资源                   | 用途                              |
| ------------------------------- | --------------------------------- |
| `/engine/status`                | Engine 运行态快照                 |
| `/tasks`、`/task <id>`          | Task 列表与详情                   |
| `/agents`、`/agent <id>`        | Agent 列表与详情                  |
| `/events`、`/event <AMP JSON>`  | 因果事件查询与 AMP 注入           |
| `/pump`                         | 显式推进 1–100 个 turn            |
| `/say <text>`                   | 提交会话消息                      |
| `/memory/status`                | 记忆统计与降级状态                |
| `/log`、`/clear`、`/quit`       | Console 进程操作                  |
| `/help`                         | 从 OperationSpec 生成操作目录     |

Panel backend 默认绑定 `127.0.0.1:8765`，定位为本地、单 owner、单 engine：

- `/healthz` 无认证；
- bootstrap token 登录换取 Bearer 或同源 HttpOnly session cookie；
- 其余页面、Lab、操作、附件和 WebSocket 需要 session；
- WebSocket 额外校验 Origin，并按 cursor 推送与 Console 同源的输出流；
- 完整浏览器前端位于独立 `AuroraBot-panel` 仓库，开发服务器默认使用 8766。

它不是公网多租户服务，也不应直接暴露到不受信任网络。

## 9. 持久化与恢复

```text
data/
  engine/runtime.sqlite3        Task、Agent、消息、Activity、Inbox、lane、因果事件、输出
  ai/cost.sqlite3               模型费用
  memory/memory.sqlite3         window、summary、durable facts、记忆回执
  memory/mem0-history.sqlite3   mem0 历史
  memory/chroma/                向量索引
  ops/panel.sqlite3             Panel session 与附件索引
  ops/Token.txt                 bootstrap token
  ops/uploads/                  附件文件
  platform/mcp/apps/            MCP App 私有数据
```

SQLite 使用 WAL 与连续 schema migration。运行时不读取历史 JSON/JSONL、文件 Inbox 或旧工作区格式。

启动恢复时：

- `PROCESSING` 消息回到 `PENDING`；
- `TRIAGING` Inbox 事件回到 `PENDING`；
- 中断的 model Activity 结束并产生 `model.failed`；
- tool Activity 保留，交给 ToolRegistry 恢复并依赖回执幂等。

终态 Task 和因果记录当前保留在数据库中。可执行 TTL、WAL checkpoint/清理、跨 engine/memory/ai/ops 的一致备份与恢复仍属于路线图。

## 10. 配置与启动

配置加载顺序：核心 TOML → `runtime.profile` 覆盖 → 路径解析与跨文件校验 → 不可变 `AuroraConfig`。未知键、越界或重叠路径、
非法 Platform、无效 App 和未声明 Prompt 都会在加载时失败，而不是静默采用默认值；模型密钥缺失则在对应角色实际调用前给出明确错误。

```powershell
git clone --branch nightly --single-branch https://github.com/AuroraBot-Dev/AuroraBot.git
Set-Location AuroraBot
uv sync --no-dev
Copy-Item .env.example .env
```

当前默认启用仓库外的 `org.aurora.qq` App。未安装 `extensions/apps/Aurora-QQ` 时，须先在 `config/apps.toml` 对应条目设置
`enabled = false`。填写 `DEEPSEEK_API_KEY` 后启动：

```powershell
uv run --no-dev --env-file .env aurora start
```

`--headless` 只关闭 Console。重复的 `--platform` 构成精确集合，不与 `config/platforms.toml` 默认值叠加。

## 11. 改动入口与质量门

| 改动                  | 首要位置                         | 约束                                      |
| --------------------- | -------------------------------- | ----------------------------------------- |
| 新 DTO 或 Port        | `src/contracts`                  | 先更新 RFC 0300，补边界/契约测试          |
| 新决策或状态迁移      | `src/engine/store`               | 保持事务原子、恢复、幂等和 generation 屏障 |
| 新 Agent 行为         | `src/agents` + prompts/profiles  | handler 仍只做 context → decision         |
| 新模型角色            | `src/ai/roles`                   | 自包含 endpoint 与适配，补 gateway 测试   |
| 新 MCP App            | `config/apps.toml` 或 extensions | 显式配置、稳定 package、环境变量白名单    |
| 新 Platform           | contracts + platform + aurora    | Platform 不依赖 engine/ops                |
| 新操作                | contracts/operation + ops        | REST 与文本入口同构                       |
| 数据库变更            | models/schema + migration        | 连续迁移、回滚和当前形状测试              |

提交前运行：

```powershell
uv run aurora check
```

测试应离线、确定且可重复；Provider、时钟和 MCP 使用 fake。运行时语义变更还应验证事务边界、幂等、因果父子关系、恢复与晚到结果隔离。
