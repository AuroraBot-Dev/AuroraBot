# 0204：Console 本地交互前端（脱离平台抽象）

状态：已接受
日期：2026-08-05
来源：要求 Bot 不调用工具也默认在 Console 输出，同时保持平台抽象只覆盖外部生态

## 问题

Console 在平台抽象中的位置只剩一个事实：输出侧通过 `org.aurora.console.send` 工具 executor 投递。
输入侧早已脱离平台——`run_console` 直接调用 `ConsoleControlPort.route_input()` 进入 ops
（shell.py:120-132），从不经过平台 AMP 入口。由此产生两个结构性缺口：

- 模型纯文本只会进入 `Completion`（src/agents/handler.py:198-205），不会路由到任何平台；Bot 文本必须
  由模型调用 send 工具才可见，与"Console 是本地交互面"的直觉相反。
- 平台抽象的定义是"输入与外部效果适配器"（RFC 0200），面向 Dashboard、MCP 等外部生态。Console 是
  进程本地 stdin/stdout 交互面，放进平台集合既误导工具注册，也迫使本地输出走外部效果契约
  （capability、schema、幂等台账、receipt、`complete_task`）。

## 决定

### Console 脱离平台抽象

- 删除 `src/platform/console/`，新增 `src/console/` 作为运行时本地交互前端，职责为交互 Shell 与
  输出渲染，与 ops 同级、位于热路径之外。
- 删除 `org.aurora.console.send` 能力、`complete_task` 参数、`ToolExecutorBinding`、SQLite 幂等台账
  与 `storage.platform.console` 路径。Console 不再拥有任何 Tool executor。
- `ConsolePreference` 从 `PlatformPreference` 移除；`PLATFORM_NAMES` 只包含 dashboard 与 mcp。
- `--platform console` 不再合法；平台选择与 Console 无关。
- `--headless` 只抑制 Console，不改变平台组合：平台仍由 `--platform` 或偏好决定，默认按偏好启用。
  无头模式与 `--platform` 可自由组合。

### 输出改为渲染

- Console 是只读渲染器，不进入 engine 热路径：contracts 新增窄查询端口（如 `RuntimeQueryPort`），
  由 engine 门面实现，注入 Console；按游标返回用户可见文本（model 文本、Completion summary、
  failure），Console 后台循环拉取并打印 `Bot> ...`。
- 任何会话产生的用户可见文本都被渲染：Console 同时是本地开发者监察面，不为各会话做权限过滤。
- 没有投递就没有去重问题：模型既调 send 工具又留结束语的双输出冲突从根上消失。
- 输入路径不变：继续经 ops `route_input` 处理普通会话与斜杠命令。

### 配置与 CLI 语义

- `[platform.console]` 迁移为 `[runtime.console]`（runtime.toml）：`enabled`（默认 true）、
  `terminal_logs`（是否在终端输出运行时日志）。Console 属于运行时配置，天然可被 profile 覆盖。
- `storage.platform.console` 与台账数据库路径一并删除，不再保留旧路径的隐式兼容读取。

### 进程组合与生命周期

- aurora 组合根不再通过 `PlatformHandle` 注册表管理 Console；默认启动，当 `--headless` 或
  `[runtime.console].enabled = false` 时不启动。
- Console 停止语义不变：EOF / Ctrl+C / 斜杠命令仍请求组合根统一关闭流程。
- engine 的 tool 派发、任务结束与收尾流程不受影响：模型结束一轮仍通过 `Completion`，文本由
  Console 渲染而非投递。

## 对其他 RFC 的修订

- RFC 0200 包边界表格新增 `src/console`（交互 Shell 与输出渲染，可依赖 contracts、utils，经窄端口
  查询 engine），并把 `src.platform` 的定义收窄为外部生态适配器（Dashboard、MCP）。
- RFC 0203 不受影响：平台回复工具的 `runtime_completion` 契约仍适用于 Dashboard 等外部平台，仅
  Console 不再拥有回复工具。

## 结果

Bot 文本默认出现在 Console，无需任何工具调用；Console 保持本地交互前端地位，平台抽象只覆盖外部
生态；热路径零侵入，幂等台账与恢复逻辑随 executor 一起删除。
