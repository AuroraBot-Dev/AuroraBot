# AuroraBot 演化路线图

状态：0.6 alpha；七端口扩展基线已合并，进入契约闭环、可预测交付与长期运行阶段
日期：2026-08-17
设计基准：[RFC 0300](docs/rfc/0300-unified-architecture-and-contracts.md)

## 1. 当前判断

AuroraBot 已完成 Agent 中心运行时、会话双工与七端口扩展贡献模型的主体迁移。`ExtensionManifest`、
`ExtensionFace`、`CapabilityAssembly`、`extensions.toml` 和 `capability.*` 保留事件已经进入 `nightly` 主线；Memory、
Console、Panel 与 MCP 也已显式映射到对应贡献面。下一阶段不再扩大架构名词，而是先让 RFC、公共 contracts、组合根和
测试对每个贡献面的生命周期、装配与恢复给出同一答案。

2026-08-17 验证基线：

- 当前版本为 `0.6.0`，Git 基线为 `v0.6.0-alpha.5`；
- `uv run aurora check` 全部通过：242 个测试，语句覆盖率 84.43%；
- Ruff、format、Pyright、依赖边界、Schema v10 迁移、Triage、generation 提交屏障、多 Tool call、费用持久化、
  Panel HTTP 认证与扩展声明装配均有回归测试；
- 项目仍是 alpha：不承诺公网多租户、无人值守生产运行、稳定第三方进程内 ABI 或长期数据治理。

## 2. 架构更新审计

### 已对齐

1. 七类贡献端口已经进入 contracts：`InputGateway`、`EventSource`、`ControlAction`、`ContextContributor`、
   `EffectTool`、`OutputSink`、`Projector`。
2. 内建 control 与 memory 扩展由 `extensions.toml` 声明，factory 只命中组合根注册表；版本、faces、capabilities 与
   manifest 不一致时启动失败。
3. Memory recall/remember/terminal projection 分别映射为 ContextContributor、EffectTool 与 Projector；Console 与
   Panel 输出消费映射为 OutputSink；MCP 通过 PlatformHandle 暴露 EventSource 与 EffectTool。
4. `capability.registered` 采用稳定幂等键，只写因果事件、不进入 Inbox；保留事件族已由 contracts 约束。
5. 工具回执公共契约统一为 `tool.succeeded` / `tool.failed` / `tool.unknown`，文档不再使用未实现的
   `tool.rejected` 名称。

### 尚未闭环

1. RFC 的 Lifecycle 语义包含 mount/unmount/health/recover；现行 `ExtensionLifecycle` 仍是
   start/shutdown/status，PlatformHandle 又使用 server/cleanup，尚未统一成一套生命周期契约。
2. RFC 要求 Manifest 携带信任域与 EffectTool 授权策略附件；现行 `ExtensionManifest` 只有 id、version、faces、
   capabilities 与 builtin 标志。
3. `CapabilityAssembly` 当前统一装配内建 ControlAction、ContextContributor、EffectTool 与 Projector；
   InputGateway、EventSource、OutputSink 和平台生命周期仍由既有组合路径接入，尚未形成 RFC 所述的单一装配结果。
4. `capability.unavailable` 与 `capability.health_changed` 已保留但没有完整发布、恢复和查询闭环。
5. 默认配置仍启用仓库外 Aurora-QQ；App 工作目录、命令和必需环境变量也没有全部在创建子进程前完成预检。
6. Panel HTTP 认证已有测试，但 WebSocket token/cookie、Origin、断连和 cursor 的端到端契约测试仍缺失。
7. 供应商瞬时事件过滤尚未形成核心 TOML 契约；长期 TTL、备份恢复、故障注入与 soak test 也未完成。

## 3. 优先级

### P0：扩展契约闭环

1. [ ] 统一 ExtensionLifecycle 与 PlatformHandle 的启动、健康、恢复和关闭语义，并补失败回收测试。
2. [ ] 补齐 Manifest 的信任域与 EffectTool 授权策略，或先修改 RFC 明确删减后的稳定公共形状。
3. [ ] 让 CapabilityAssembly 产出七类贡献与生命周期的单一装配快照，移除平行的隐式装配路径。
4. [ ] 为七类贡献分别增加重复检测、边界、关闭与恢复测试。
5. [ ] 实现 `capability.unavailable` / `capability.health_changed` 的稳定发布与查询投影。

完成门槛：RFC、contracts、组合根和测试使用同一 Manifest/Lifecycle/Assembly 形状；每个已启用贡献都能从声明追踪到
实现、运行状态、因果事件和有界关闭路径。

### P1：可预测交付

1. [ ] 默认关闭未随仓库交付的 Aurora-QQ App，保证干净克隆不依赖仓库外目录。
2. [ ] 在创建 MCP 子进程或远程会话前验证工作目录、命令、HTTPS URL 和必需环境变量，并指出具体 App。
3. [ ] 补齐 WebSocket Bearer/cookie、Origin、断连、尾游标和增量顺序测试。
4. [ ] 实现供应商瞬时事件的 TOML 过滤契约，并验证过滤只发生在外部归一化边界。
5. [ ] 为 `extensions.toml` 禁用项增加 profile/能力引用诊断，避免在更晚阶段失败。

完成门槛：干净克隆按快速开始可预测启动；错误 App 配置不创建进程；Panel 全部受保护入口都有认证与断连证据。

### P2：长期运行与恢复

1. [ ] 实现由 ops 触发的终态 TTL、会话导出、WAL checkpoint 和清理操作。
2. [ ] 费用统计改为数据库聚合或有界缓存，避免启动加载完整历史。
3. [ ] 建立 engine、memory、ai、ops 数据库的一致备份与恢复流程。
4. [ ] 增加迁移失败回滚、进程中断、工具重复回执和 MCP 断线故障注入。
5. [ ] 建立 24/72 小时 soak test，观察队列、Task、Activity、数据库和后台任务增长。

完成门槛：72 小时测试无无界队列、后台任务泄漏或非预期数据库增长；可以从备份恢复并继续消费已有 Activity；清理后
外部消息与工具回执幂等仍成立。

### P3：演化成本与能力扩展

1. [ ] 按状态迁移、查询和批次职责拆分 972 行的 `src/engine/store/decisions.py`。
2. [ ] 按本地/远程连接、通知、发现和执行职责拆分 539 行的 `src/platform/mcp/adapter.py`。
3. [ ] 把附件引用解析、MIME 校验、内容读取和 multimodal role 串成完整链路。
4. [ ] 为第三方 MCP App 建立版本、兼容性、健康检查和开发者脚手架。
5. [ ] sandbox 启用前完成威胁模型、权限策略、资源限制、产物回收和因果回执。

## 4. 里程碑

### M0：Agent 热路径与会话正确性（已完成）

- [x] 完成 AgentEngine、Activity、因果 SQLite 与连续 Schema v10 迁移。
- [x] 完成异步 MemoryStore、语义/关键词降级和统一字符预算。
- [x] 完成 fast/root Triage、revision/watermark/delta、提交屏障与有界抢占。
- [x] 完成多 Tool call、即时补槽、跨 session 公平调度和晚到结果隔离。
- [x] 将 `ops/` 纳入 Ruff、format、Pyright 与 coverage。

### M1：七端口契约收口（1–3 周）

- [x] 引入七端口 contracts、Manifest、extensions.toml 与 CapabilityAssembly 基线。
- [x] 映射 Memory、Console、Panel 和 MCP 的现行贡献面。
- [x] 建立 `capability.*` 保留事件族与 `capability.registered` 幂等回归。
- [ ] 收敛 Manifest 元数据与 Lifecycle 公共形状。
- [ ] 形成七端口单一装配快照及完整重复/边界测试。
- [ ] 闭合 unavailable/health_changed 的发布、投影与恢复语义。

### M2：交付与真实集成（2–5 周）

- [ ] 关闭默认外部 App 依赖并重验快速开始。
- [ ] 完成 MCP App 启动预检与供应商事件过滤。
- [ ] 完成 Panel WebSocket 认证、Origin、断连与 cursor 契约测试。
- [ ] 建立 fake Provider + 真实 stdio MCP 子进程的确定性 E2E。
- [ ] 为自主心跳、Triage、委派、多 Tool call、恢复和会话导出建立黄金路径。

### M3：长期运行与 0.6 Beta（5–10 周）

- [ ] 提供 TTL、checkpoint、清理、备份与恢复操作。
- [ ] 增加关键指标、故障注入和 24/72 小时 soak test。
- [ ] 拆分超过 500 行且职责混杂的主源码文件。
- [ ] 让 Python 3.12–3.14 CI 全绿；当前 CI 只覆盖 3.12 与 3.13。
- [ ] 发布 0.6 beta，并提供 alpha 数据目录升级说明。

### M4：0.7 能力扩展（Beta 后）

- [ ] 完成附件多模态链路。
- [ ] 提供启用 Clock 的主动节律 profile 和可验证自主 Task 示例。
- [ ] 发布 MCP App 兼容、健康与脚手架规范。
- [ ] 在威胁模型与授权闭环后决定是否启用 sandbox。

### M5：1.0 稳定性

- [ ] 版本化 AMP、Operation、配置与数据迁移兼容范围。
- [ ] 固化备份、恢复、保留、安全和性能基准。
- [ ] 发布稳定扩展指南和升级指南。
- [ ] 继续保持 loopback、单 owner、单 engine 的部署模型；多租户若进入目标，必须先修改 RFC 0300 的进程与安全边界。

## 5. 暂不优先

- 不再次重写 engine；优先关闭现有 RFC 与实现差距。
- 不在 0.6 alpha 阶段承诺公网多租户。
- 不在扩展生命周期、默认交付、TTL、MCP 恢复和 E2E 尚未闭环前继续扩大能力数量。
- 不以降低测试门槛或放宽边界检查换取发布速度。
