# RFC 0014：并行平台组合与偏好配置

状态：已接受
日期：2026-07-19

## 背景

RFC 0013 使用 `dev`、`run`、`serve` 和 `console` 子命令表达固定进程组合，但 Console、Dashboard 和 MCP
实际上是可以独立启用的三个外部平台。固定模式会随组合数量增长，并使 `AuroraRuntime` 知道具体 surface、日志
偏好和平台生命周期。

当前 Dashboard 的 HTTP、WebSocket 与聊天持久化分散在 `src.dashboard` 和 `src.localhost`；Console 输入位于
localhost，但输出通过内建 Console MCP App 返回，同时还保留一套未承担实际输出的 `ConsolePlatform`；MCP
notification 则可以绕过 localhost ingress 直接投递 Kernel。这些路径虽然大体遵守静态依赖测试，却没有形成三种
平台一致的输入、效果与生命周期边界。

项目还需要把影响 Kernel、模型、存储和安全的核心配置，与只决定本地启动组合和界面体验的个性化偏好分离，
同时保持 TOML 快照可验证、无隐式任意覆盖。

## 决策

### 核心配置与偏好配置

配置目录使用以下文件：

```text
config/aurora.toml          Kernel、Agent 运行限制、scheduler、SOUL、存储、日志、模型与平台安全约束
config/platforms.toml       平台默认组合、本地体验偏好与平台私有配置
config/agents.toml          Agent profile、授权能力与委派边界
config/apps.toml            MCP App、transport、工具 allowlist 与启用状态
config/profiles/<name>.toml 仅覆盖 aurora.toml 的环境差异
```

`aurora.toml` 与 `platforms.toml` 必须解析为两个独立、不可变且可追踪来源的配置快照，不得递归合并为一个任意
覆盖树。profile 只覆盖 `aurora.toml`；环境变量除 `AURORA_PROFILE` 和密钥注入外不得覆盖任一 TOML 字段。

`platforms.toml` 包含两类配置：以 `[platform.*]` 命名的平台启用与本地体验偏好，以及以 `[dashboard]` 等命名的
平台私有安全与持久化配置。

`[platform.*]` 初始拥有以下形状（dashboard 同时承载本地偏好与服务器私有配置）：

```toml
[platform.console]
enabled = true
terminal_logs = false

[platform.dashboard]
enabled = true
open_browser = false
host = "127.0.0.1"
port = 8000
database_path = "data/platform/dashboard/chat.sqlite3"
upload_dir = "data/platform/dashboard/uploads"
max_upload_bytes = 67108864
session_ttl_seconds = 604800
allowed_origins = ["http://localhost:5173"]

[platform.dashboard.owner]
username = "admin"

[platform.dashboard.bot]
username = "aurorabot"
display_name = "AuroraBot"
avatar_url = ""

[platform.mcp]
enabled = true
terminal_logs = true
```

`[platform.*]` 只控制启动选择和本地呈现。Dashboard host、port、allowed origins、数据库与上传路径，Kernel
workspace，文件日志级别，MCP command、timeout、认证和能力声明仍属于核心或领域配置，使用各自独立 section。
新增 `[platform.*]` 键必须有明确类型、默认值和所属平台；未知键必须在启动前失败。

`terminal_logs` 是启动默认值，不是持久化的当前会话状态。运行时 `/log on|off` 仍只修改当前进程，不回写
`platforms.toml`。Console 的 `terminal_logs` 控制进程启动时的全局终端日志开关；MCP 的 `terminal_logs` 进一步
控制 MCP 子进程诊断是否可进入已开启的终端 handler，文件诊断不受影响。

### 平台选择 CLI

运行入口统一为：

```text
aurora [--console] [--dashboard] [--mcp]
aurora --headless
aurora check
```

`--root` 与 `--profile` 继续选择配置上下文。平台选择规则必须确定且只解析一次：

1. 未出现平台选择参数时，使用 `platforms.toml` 中 `[platform.*]` 的三个 `enabled` 值。
2. 出现任意 `--console`、`--dashboard` 或 `--mcp` 时，启动集合恰好是显式列出的平台，不与默认集合叠加。
3. `--headless` 表示空平台集合，并与三个平台参数互斥。
4. `check` 保留为非运行时质量命令，不得创建 Runtime 或平台资源。

删除 `dev`、`run`、`serve` 和 `console` 运行时子命令，不提供长期双入口或兼容别名。无论选择何种组合，每个
进程都只有一个 `AuroraRuntime`、一个 Kernel 所有者、一个共享 stop event 和一条关闭路径。

### 三个平台的并行边界

Console、Dashboard 与 MCP 是平行的外部平台适配器：

| 包 | 平台私有职责 |
| --- | --- |
| `src.platform.console` | stdin shell、终端输出、Console session 与 Console effect |
| `src.platform.dashboard` | HTTP、WebSocket、鉴权、聊天与附件持久化、Dashboard effect |
| `src.platform.mcp` | stdio/Streamable HTTP、进程与连接管理、能力发现、notification 与 MCP effect |

删除独立的 `src.dashboard` 包。现有 Dashboard API、security、chat service、store 和 routing 必须整体归入
`src.platform.dashboard`；Dashboard SQLite 与附件仍是 Dashboard 平台数据，不进入 Kernel workspace。

删除内建 `org.aurora.console` MCP App。`ConsolePlatform` 直接拥有 `org.aurora.console.send_message`，并把成功
结果送到自己的输出队列；Console 不再为内建终端启动 MCP 子进程。MCP 只承载真实 MCP App 和远程 MCP 服务。

三个平台可以共享无平台语义的轻量契约，但不得通过继承体系合并私有生命周期、协议对象或持久化实现。

### 应用端口与依赖方向

`src.localhost` 是传输无关的应用与运行时层，拥有命令路由、统一 ingress、scheduler、模型 Activity dispatcher
和 effect dispatcher。它声明供外部适配器调用或实现的窄公共端口；具体平台不得导入 Kernel 实现或具体
`AuroraRuntime`。

源代码依赖方向调整为：

```text
utils/contracts <- kernel/ai/agents <- localhost <- platform <- aurora
```

其中 `kernel`、`ai` 和 `agents` 仍是相互独立的内层包；箭头只表示外层允许依赖左侧公开契约。具体要求为：

- Kernel 只依赖 contracts 与 utils，不理解平台名称或私有对象。
- localhost 可以依赖 Kernel、AI、Agent 与 contracts，但不得导入具体 `src.platform.*` 实现。
- platform 可以依赖 localhost 公开端口、contracts 与 utils，但不得直接依赖 Kernel 实现。
- `aurora` 是唯一可以同时导入 localhost 与具体平台并完成实例化、注入、启动和关闭的组合层。
- `src` 不得导入 `aurora`。

localhost 至少提供三个窄边界：交互输入路由、外部 AMP ingress 和效果执行。具体 Python 名称不构成本 RFC 的
稳定 API，但一个平台不得因此获得查询或修改任意 Kernel 状态的宽端口。

### 输入与效果闭环

Console 和 Dashboard 文本必须通过同一个 localhost 交互输入端口，继续共享 `RuntimeInput`、命令目录与
`CommandResult`。MCP notification 必须通过 localhost 外部 AMP ingress，以统一触发 wake、scheduler 外部活动、
自主 Task 取消和因果接管；不得直接持有 Kernel ingress。

效果闭环为：

```text
Kernel effect Activity
  -> localhost effect dispatcher
  -> 唯一匹配的已启用 Platform executor
  -> EffectOutcome
  -> localhost 提交新的 effect.succeeded 或 effect.failed AMP
  -> Kernel 在后续 pump 恢复原 Agent
```

Platform 是唯一执行环境效果的一层；localhost 只负责领取、路由和持久化平台返回的结构化结果。平台不得直接
完成 Activity 或修改 Agent 状态。效果执行失败，包括 MCP 明确返回的 tool error，必须形成 `effect.failed`，不得
记为成功回执。

Agent profile 中声明的 capability 是授权上限，不代表对应平台必须在每次启动中启用。活动 capability catalog
只由已启用平台和已启用 MCP App 组成；对当前未启用 capability 的请求必须确定性失败，但不得仅因某个已授权
平台未启动而拒绝整个进程配置。

### 生命周期与组合

`aurora` 根据解析后的平台集合只构造所选适配器。禁用的平台不得初始化数据库、打开 socket、启动 reader thread、
创建 MCP 子进程或注册活动 capability。平台启动失败必须进入共享关闭路径，已经启动的平台按逆序释放资源。

AuroraRuntime 不得加载 `platforms.toml`、解析 CLI、选择平台、配置终端日志或构造具体平台。它接收已验证的核心
配置以及通过 localhost 端口注入的活动平台能力。日志 bootstrap 必须在可能产生日志的 Runtime 和平台构造之前由
`aurora` 完成。

## 约束与非目标

- 平台选择在进程启动时固定；本 RFC 不提供运行中热启停或动态重载 platform preference。
- `platforms.toml` 中的 `[platform.*]` section 不保存 PID、租约、会话命令状态或其他运行数据。
- 本 RFC 不改变 Kernel 的 `data/kernel/{inbox,process,archive}` 工作区和 SQLite WAL 契约。
- 本 RFC 不定义第三方 Python 平台插件发现；三个内建平台仍由 `aurora` 显式构造。
- 本 RFC 不允许 preference 改写安全、审计、存储、模型、Agent 或 MCP 能力契约。
- Dashboard 前端仍由独立工程维护，本仓库只拥有后端平台适配器。

## 与既有 RFC 的关系

本 RFC 部分取代以下已接受决策，未提及的条款继续有效：

- 取代 RFC 0001 和 RFC 0012 中 `platform <- localhost <- dashboard` 的包方向及独立 `src.dashboard` 布局。
- 取代 RFC 0002 的配置文件清单，将偏好配置整合入 `platforms.toml`，同时新增独立的 `platforms.toml`，
  但保留 TOML、profile、密钥和来源审计规则。
- 取代 RFC 0004 将本地 Console 实现为 `org.aurora.console` MCP App 的决定。
- 取代 RFC 0006、RFC 0007 和 RFC 0010 对 Console shell、Dashboard API 与聊天用例包位置的决定。
- 取代 RFC 0009 和 RFC 0013 的 `dev`、`run`、`serve`、`console` 固定运行模式与子命令。
- 保留 RFC 0001、RFC 0012 的 Kernel、Agent、Activity、因果边界和 Platform 唯一效果执行权。
- 保留 RFC 0013 的统一斜杠命令、单 Runtime、共享 stop event、Dashboard 命令幂等和 `/log` 会话语义。

## 验收标准

1. `config/aurora.toml` 与 `config/platforms.toml` 分别产生严格、不可变且可追踪来源的配置快照，不能跨文件任意覆盖。
2. 无平台参数时使用 preference 默认；显式平台参数形成精确集合；`--headless` 形成空集合；旧运行时子命令不存在。
3. 任意平台组合只创建一个 Runtime/Kernel，并且禁用平台不产生线程、socket、数据库或子进程副作用。
4. `src.dashboard` 不存在，Dashboard 后端、聊天持久化和效果执行完整位于 `src.platform.dashboard`。
5. Console 输入和输出完整位于 `src.platform.console`，不启动 `org.aurora.console` MCP App，终端效果仍只显示一次。
6. 三个平台只通过 localhost 窄端口交换输入和效果，不导入或直接调用 Kernel 实现。
7. Console 与 Dashboard 继续共享命令语义；MCP notification 经过统一 ingress 并立即唤醒 Runtime。
8. 每个 effect 只由一个活动平台执行，成功与失败均以新 AMP 回流，MCP tool error 不得成为成功回执。
9. CLI 显式选择覆盖 preference 的 enabled 集合但不修改文件；`/log` 调整不跨进程持久化。
10. wheel 可从空目录显示 CLI 帮助和执行 `check`；依赖、配置、组合和平台资源边界均有自动化测试。
