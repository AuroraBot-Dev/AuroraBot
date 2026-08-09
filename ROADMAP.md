# AuroraBot 演化路线图

状态：P0 已收口；进入长期运行与真实集成阶段
日期：2026-08-09
设计基准：[RFC 0300](docs/rfc/0300-unified-architecture-and-contracts.md)

## 1. 当前判断

AuroraBot 已完成 Agent 中心运行时的主体迁移：engine、contracts、ops、MCP、记忆、模型网关和因果存储均有现行
实现及回归测试。下一阶段不再进行无目标的架构重写，而是依次完成契约闭环、长期运行、真实集成验证和能力扩展。

最近一次已验证质量基线：

- 完整质量命令通过，224 个测试通过；
- `aurora`、`ops` 与 `src` 总语句覆盖率为 83.84%；
- 依赖边界、SQLite 迁移、Triage、工具回执、多 Tool call、面板操作和费用持久化已有测试；
- 项目仍处于 0.5 alpha，尚不应承诺公网多租户或无人值守生产运行。

## 2. 优先问题

### P0：契约与正确性（2026-08-09 已完成）

1. [x] 组合根将配置的 embedding 与 quality 模型注入 LongTermMemory；recall 语义优先、durable facts 关键词降级。
2. [x] MemoryStore 改为异步 Port，概要直接 await fast role，SQLite、mem0 与同步 embedding 移到工作线程。
3. [x] `MemoryQuery.max_characters` 统一约束 summary、window 与 relevant facts，并采用确定性选择和裁剪顺序。
4. [x] Panel Lab、静态资源与 `/api/health` 要求有效 session；登录设置同源 HttpOnly cookie，Bearer 仍受支持。
5. [x] `aurora check` 的 Ruff、format、Pyright 与 coverage 已覆盖根级 `ops/` 包。

收口证据：异步 LLM 概要、模型注入、scope 语义检索、关键词降级、统一预算、Lab 认证和质量命令范围均有回归测试；
memory 已按纯数据 models、短期算法 short_term、异步编排 service 拆分。当前完整质量门为 224 tests / 83.84% coverage。

### P0：会话双工与响应时效（2026-08-09 已完成）

1. [x] 在唯一 RFC 中定义 observed/generation/committed revision、watermark、delta、提交屏障和有界抢占。
2. [x] Triage 获权选择 `builtin.fast` 快脑或 `builtin.root` 主脑；非法、缺失与 fail-open 保守进入 root。
3. [x] Schema v10 以 `session_lanes` 持久化 session revision、generation watermark 与唯一活动交互 Task。
4. [x] 新 AMP 按优先级进入 delta；只有直接点名、明确纠正或语境失效事件请求抢占，且限制抢占次数和总等待。
5. [x] 将 Activity supersede 原子状态传播到 asyncio 与 Provider 流取消，并以 Task/lane/revision 屏障拒绝晚到结果。
6. [x] 工具回执与用户输出增加 generation 提交校验；不可撤回平台只读取 `output_publications` 单调提交流。
7. [x] 移除模型与工具派发的整批完成屏障，实现空闲槽即时领取、交互优先和跨 session 公平调度。
8. [x] 覆盖持续群聊、重要消息插队、抢占封顶、晚到结果隔离和不可取消工具效果的确定性场景。

完成门槛（已达到）：持续普通群聊下 Bot 能在有界时间内插话；直接交互可打断未提交的旧生成；任何 superseded generation 都不能
产生用户可见输出或新的外部效果；单一高流量 session 不得饿死其他会话。

收口证据：普通 delta 在当前 generation 运行时持续积累但不阻止其提交；定向纠正会取消旧 Provider 协程并重建包含完整
上下文的 generation；抢占次数达到上限后当前回复必须完成；PROCESSING 的不可撤回工具阻止抢占；模型和工具槽位释放后
无需等待同批慢任务即可领取其他 session。Schema v9 可连续迁移到 v10，旧 generation 永不进入用户输出提交流。

### P1：长期运行与交付

1. 默认配置启用仓库外 Aurora-QQ 扩展，干净克隆无法保证默认组合自洽。
2. 供应商瞬时事件的 TOML 过滤契约尚未在核心平台配置中闭环。
3. 终态 Task、因果事件和费用记录缺少可执行的 TTL、聚合与清理操作。
4. MCP 子进程生命周期、断线恢复、长期记忆和角色适配的真实集成覆盖不足。
5. README、提示词和部分技术文档仍带有历史 Dashboard、Responses 和版本描述。

### P2：演化成本

1. `src/engine/store/decisions.py` 与 `src/platform/mcp/adapter.py` 超过 500 行，需要按领域职责拆分。
2. 附件目前完成存储和引用传递，但尚未形成多模态理解链路。
3. sandbox 和 speech 保持未启用或占位状态，尚未完成运行时授权与效果回执设计。

## 3. 里程碑

### M0：设计与交付收口（1–2 周）

目标：使唯一 RFC、实现、配置和用户文档指向同一系统。

[x] 建立 RFC 0300 条款到实现与测试的可追踪矩阵。
[x] 清理 README、TECHNICAL、Prompt、扩展指南和配置样例中的历史概念。
[x] 将 `ops/` 纳入 Ruff、format、Pyright 和 coverage，增加文档相对链接检查。
[ ] 默认关闭未随仓库交付的外部 App，增加干净克隆启动说明。
[x] 为 Panel Lab 和记忆预算补充契约测试。
[ ] 为 WebSocket token、Origin、断连、游标和事件过滤补充契约测试。

完成门槛：

[x] 全仓不存在旧编号 RFC 引用；
[x] 无已知“RFC 0300—实现”冲突未登记；
[ ] 干净克隆可按默认文档完成可预测启动；
[x] `aurora check` 覆盖所有一方 Python 包。

### M1：核心正确性（2–4 周）

目标：闭合记忆、认证和平台摄入的核心承诺。

[x] 重构 MemoryStore 的异步边界，并拆分 models / short_term / service，确保摘要和语义 I/O 不阻塞 engine 事件循环。
[x] 将模型配置、同步 embedding 和语义 search 注入 LongTermMemory。
[x] 合并语义结果与 durable facts 降级，并公开健康与降级状态。
[x] 对 summary、window、facts 实施统一字符预算和确定性裁剪。
[x] 保护 Lab，并支持 Bearer 与同源 HttpOnly session cookie。
[ ] 补齐 WebSocket token、Origin、断连和游标测试。
[ ] 为 App 工作目录、命令、URL 和环境变量增加启动前置检查。
[ ] 实现可配置的供应商瞬时事件过滤。

完成门槛：

[x] 记忆窗口、LLM 概要、语义适配、关键词降级可通过确定性集成测试验证；
[x] engine pump 内不存在同步网络调用；
[x] Panel 除 `/healthz` 与 bootstrap 登录交换外的 HTTP 端点经过 session 认证测试；
[ ] 错误 App 配置在创建子进程前给出明确诊断。

### M2：长期运行与恢复（4–8 周）

目标：把“可以运行”提升为“可以持续运行并恢复”。

[ ] 实现由 ops 触发的终态 TTL、会话导出、WAL checkpoint 和清理操作。
[ ] 费用统计改为数据库聚合或有界缓存，避免启动加载完整历史。
[ ] 建立 engine、memory、ai、ops 数据库的一致备份与恢复流程。
[ ] 增加迁移失败回滚、进程中断、工具重复回执和 MCP 断线故障注入。
[ ] 建立 24/72 小时 soak test，观察队列、Task、Activity、数据库和后台任务增长。

完成门槛：

[ ] 72 小时测试无无界队列、后台任务泄漏或非预期数据库增长；
[ ] 支持从备份恢复并继续消费已有 Activity；
[ ] 清理后外部消息与工具回执幂等仍成立。

### M3：可观测与 Beta（6–10 周）

目标：形成可诊断、可回归的 0.5 beta。

[ ] 在现有 ops 操作树中提供队列深度、Task 延迟、模型/工具耗时、失败率、记忆降级和存储容量投影。
[ ] 建立 fake Provider + 真实 stdio MCP 子进程的确定性 E2E 测试。
[ ] 为自主心跳、Triage、委派、多 Tool call、恢复和会话导出建立黄金路径场景。
[ ] 按状态迁移、查询和批次职责拆分 engine decisions。
[ ] 按本地/远程连接、通知、发现和执行职责拆分 MCP adapter。

完成门槛：

[ ] Python 3.12–3.14 CI 全绿；
[ ] 核心 E2E 与故障场景稳定可复现；
[ ] 关键运行指标可从 ops 查询；
[ ] 发布 0.5 beta，并提供从 alpha 数据目录升级说明。

### M4：能力扩展（Beta 后）

目标：在稳定热路径上补充真正可用的环境能力。

[ ] 把附件引用解析、MIME 校验、内容读取和 multimodal role 串成完整链路。
[ ] 提供启用 Clock 的主动节律 profile 和可验证自主 Task 示例。
[ ] 为第三方 MCP App 建立版本、兼容性、健康检查和开发者脚手架。
[ ] sandbox 启用前完成威胁模型、权限策略、资源限制、产物回收和因果回执。
[ ] 删除无法进入授权执行链的长期占位能力。

完成门槛：

[ ] 新能力全部具备显式授权、参数 schema、预算、回执、因果记录和降级路径；
[ ] 发布 0.6，不扩大 engine 与 handler 的职责边界。

### M5：1.0 稳定性

目标：给出长期可维护的公共承诺。

[ ] 版本化 AMP、Operation、配置与数据迁移兼容范围。
[ ] 固化备份、恢复、保留、安全和性能基准。
[ ] 发布稳定扩展指南和升级指南。
[ ] 继续保持 loopback、单 owner、单 engine 的部署模型；多租户若进入目标，必须先修改 RFC 0300 的进程与安全边界。

## 4. 暂不优先

- 不再次重写 engine；优先修复现有契约差距。
- 不在 0.5 阶段承诺公网多租户。
- 不在记忆、TTL、MCP 恢复和 E2E 尚未闭环前继续扩大能力数量。
- 不以降低测试门槛或放宽边界检查换取发布速度。
