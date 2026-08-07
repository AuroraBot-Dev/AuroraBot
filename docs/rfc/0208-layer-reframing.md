# 0208：层级重定性——启动环境、基础建设、能力与运行实现

状态：已接受
日期：2026-08-07
来源：对 RFC 0200/0206 包边界的语义重审；先决条件是 RFC 0207 的主动记忆工具路径（memory 已作为 ToolExecutor 接入）

## 问题

各子包的实际职责与文档语义已有偏移，导致三个症状：

- **engine 职责失焦**：`runtime.py` 886 行，同时承担授权校验、摄入、triage、turn 并发、模型/工具派发、记忆 hook、归档、输出流、查询、shutdown 等 11 类职责，违反项目自身 500 行规则，并有 `EngineState` 与 `SQLiteRuntimeStore` 的透传包装、仅为类型提示的内部 Protocol、三套持久化（SQLite / JSON archive / JSONL session log）与 activities/causal_events 载荷重复。
- **能力接入三套语义**：memory 走自动 Port、platform 走 ToolExecutor、sandbox 孤立——同一类事物（Agent 的能力）用三种机制接入，无法回答"新能力从哪来、走哪条路"。
- **角色命名偏移**：aurora 被称作"组合层"、engine 被称作"引擎"、memory 被称作"自动服务"，包语义与逻辑角色不一致。

## 决定

### 1. 五层重定性

| 层 | 包 | 逻辑角色 | 职责 |
| --- | --- | --- | --- |
| 启动环境 | `aurora` | 进程"大前期" | 创建配置快照、组合实例、启动平台与主循环、生命周期；不承载业务实现 |
| 基础建设 | `contracts` / `config` / `ai` / `prompt` / `utils` | 高层封装 | 为某个或多个包提供稳定接口与装配物；无业务状态 |
| 能力 | `memory` / `sandbox`（未来启用） | Agent 可主动或被动调用的工具 | 实现 `contracts.tool.ToolExecutor`（主动面）；memory 另有自动投影 hook（被动面） |
| 外部接入 | `platform` / `apps` | 外部能力的兼容接入层 | 逻辑上同样是给 Agent 接 tool：实现 `ToolExecutor` + `ExternalAmpIngressPort` |
| 运行实现 | `engine` | Agent 运行的实现包 | 状态（Task/Agent/邮箱/Activity）、认知闭环（triage → claim → 决策 → 派发）、资源边界 |

### 2. 能力统一：所有执行效果 = ToolExecutor

- memory 的主动面（RFC 0207 记忆 agent）、sandbox 的代码执行、platform 的外部动作三者同构：由 Capability 生成 `ToolRequest` → engine 调度 → `ToolExecutor` 执行。
- engine 只认 `ToolRegistry` 一个执行入口，不区分"本地能力"与"平台能力"。
- memory 的被动面（自动投影）仍是 pump hook——同一能力的潜意识面，不改变存储同源（RFC 0207）。
- 新能力的接入答案固定为：实现 `ToolExecutor` → `aurora` 注册 binding → profile 授权。

### 3. engine 瘦身方向（渐进执行，不在本 RFC 定义文件级改造）

- 恢复 500 行规则：`runtime.py` 按职责拆分（授权校验、摄入、认知闭环、I/O 编排、查询投影）。
- 收敛中间层：`EngineState` 与 store 之间的透传包装（`_store_call` / `_blocking_call`）随拆包自然消失或合并。
- 删除仅为类型提示的内部 Protocol（`DecisionRuntime` / `IngressRuntime` 等），直接类型引用。
- 收敛持久化：SQLite 是运行态权威；JSON archive 与 JSONL session log 属审计/可读性用途，重估是否由热路径写入改为 localhost 侧生成物。
- 审计去重：activities 与 causal_events 载荷只保留一份权威，另一份降为轻量投影。
- 单进程语义下，租约/CAS 只保留崩溃恢复能力，不再扩展多进程假设。

### 4. 边界不变

- 依赖方向与硬边界全部保持（engine 仍只依赖 contracts + utils，aurora 仍是唯一组合根）。
- contracts 不因重定性而改变；能力统一的接口就是既有的 `contracts.tool`。

## 结果

- "新能力从哪来、走哪条路"有唯一答案：实现 `ToolExecutor` → 注册 binding → profile 授权。
- engine 职责收敛到"状态 + 认知闭环 + 资源边界"，恢复单文件 500 行上限。
- 包语义与文档一致，消除"自动服务 vs 工具 vs 平台"三种接入语义。

## 兼容性

- 纯语义重定性，无运行时行为变更。
- engine 瘦身为后续独立 RFC/PR 渐进执行，每步保持行为等价。
