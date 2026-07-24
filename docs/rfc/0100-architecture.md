# 0100：架构基准、配置与进程入口

状态：已接受
日期：2026-07-23
来源：取代 RFC 0000、0001、0002

## 核心原则

Kernel 负责事件、Task/Agent 状态、邮箱、Activity 调度与因果边界；Agent handler 负责认知；Platform 负责环境感知与
效果执行。任何一层不得替代另一层的职责。

## 模块边界

| 包              | 职责                                                       |
| --------------- | ---------------------------------------------------------- |
| `src/contracts` | 配置 DTO、AMP、Agent、模型与记忆的稳定数据契约；无上层依赖 |
| `src/config`    | TOML 加载、校验、配置注册中心与热重载；依赖 contracts |
| `src/prompt`    | 提示词目录、分层 DTO 与模型上下文呈现；只依赖 contracts    |
| `src/kernel`    | Task/Agent、邮箱、Activity、SQLite 运行态与因果限制        |
| `src/ai`        | 模型网关：角色、能力协商、调用、计费、节流与中断           |
| `src/agents`    | 同构 Agent handler；只读上下文返回无副作用 Decision        |
| `src/memory`    | 三层记忆读写服务；依赖 contracts/utils + mem0/ChromaDB     |
| `src/localhost` | 统一输入、命令路由、效果/工具调度、自主额度、调试接口      |
| `src/platform`  | Console、Dashboard、MCP 的协议适配、持久化、能力与效果执行 |
| `src/apps`      | 内建原生 MCP 应用，经 Platform 接入                        |
| `src/sandbox`   | 独立沙箱组件；当前 Agent 运行时不启用                      |
| `src/utils`     | 无上层依赖的纯通用工具                                     |

## 依赖方向

```
utils/contracts ← config ← prompt ← memory ← agents/ai/localhost/platform ← aurora
```

- Kernel 只依赖 contracts 与 utils，不理解平台名称或私有对象
- localhost 不得导入具体 `src.platform.*` 实现
- platform 不得直接依赖 Kernel 实现
- `aurora` 是唯一可同时导入所有模块并完成组合的进程层
- `src` 不得导入 `aurora`

## 进程入口

顶层 `aurora` 包是唯一进程组合与 CLI 入口。平台选择规则：

- `aurora`（无参数）：使用 `platforms.toml` 中各平台的 `enabled` 默认值
- `aurora --<platform>`：精确启用指定平台（platform 集合由 `PlatformPreference` 字段动态派生）
- `aurora --headless`：空平台集合
- `aurora check`：非运行时质量命令，不创建 Runtime

每个进程只有一个 `AuroraRuntime`、一个 Kernel 所有者、一个共享 stop event 和一条关闭路径。

## 工作区

Kernel 工作区固定为三个顶级目录：

```text
data/kernel/inbox/     # 平台投递的 AMP JSON
data/kernel/process/   # runtime.sqlite3 (WAL)、租约、中间产物
data/kernel/archive/   # 已完成/失败 Task 的规范 JSON
```

外部 AMP 与终态 Task 使用 JSON，先写临时文件再原子改名。运行态使用 SQLite WAL。

## 配置

| 文件                          | 职责                                                  |
| ----------------------------- | ----------------------------------------------------- |
| `config/aurora.toml`          | Kernel、Agent 限制、scheduler、SOUL、存储、日志、模型 |
| `config/platforms.toml`       | 平台启用、本地体验偏好、平台私有安全配置              |
| `config/agents.toml`          | Agent profile、授权能力与委派边界                     |
| `config/apps.toml`            | MCP App 连接、transport 与启用状态                    |
| `config/prompts.toml`         | 提示词片段清单                                        |
| `config/profiles/<name>.toml` | 仅覆盖 aurora.toml 的环境差异                         |

### 强制规则

- 结构性配置使用 TOML；JSON 不得承担主配置职责；YAML 不进入配置链
- `aurora.toml` 与 `platforms.toml` 各自产生不可变快照，不得跨文件任意覆盖
- profile 只覆盖 `aurora.toml`；表递归合并，标量与数组整体替换
- 密钥仅来自环境变量，TOML 只声明环境变量名（如 `secret_env = "OPENAI_API_KEY"`）
- 除 `AURORA_PROFILE` 外，环境变量不得静默覆盖 TOML
- 未知键、类型不匹配和无效引用必须在启动前失败
- 模块导入不得隐式读取配置或创建运行目录
- 配置通过 `src.config` 集中持有：`init()` 在进程早期加载，`get()` 允许所有包零参数获取不可变快照，`reload()` 支持运行时热重载并通知订阅者

## 约束

- Kernel 不理解 MCP、QQ、Discord、OneBot 或任意平台私有对象
- Dashboard 不成为第二个运行时
- 第三方 Python 插件自动发现不属于当前契约
- 守护进程、systemd、容器编排、热重载或自动重启不属于当前范围
- 平台标识符不得在代码中硬编码：全部从 `PlatformPreference` 字段派生为 `PLATFORM_NAMES`
