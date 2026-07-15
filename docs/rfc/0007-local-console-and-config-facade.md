# RFC 0007：本地控制台与共享配置门面

状态：已接受
日期：2026-07-11
修订：2026-07-15

## 背景

开发者需要通过同一套本地业务用例投递 AMP、推进周期并查询审计状态。项目内也有少量独立组件需要共享
已校验的路径、日志级别和非秘密模型标识，但这些组件不能各自建立配置来源。

## 决策

### 配置入口

`src/config.py` 是公开配置入口。它通过 `src.localhost.configuration.load_configuration()` 加载 RFC 0002 定义的
不可变 `AuroraConfig` 快照，并提供只读 `Config` 门面，供独立工具和 Provider 执行组件读取共享路径、日志级别
及模型别名。

`Config` 不从环境变量读取结构性配置，不覆盖 TOML，不授权 Node 使用模型角色，也不成为 Kernel、Platform 或 App
的隐式全局状态。模型、应用和运行图仍显式接收 `AuroraConfig` 中的领域配置。

当配置没有声明 `multimodal` 时，门面使用 `quality` 的模型标识；当配置没有声明 `embedding` 时，门面返回
`openai/text-embedding-3-small` 默认标识。这些只读别名只服务于独立组件初始化，不构成模型角色授权。

### 本地控制台

`src/localhost` 提供分层开发控制台：`registry` 声明命令、`commands` 执行业务用例、`shell` 负责交互。
它与 scheduler、模型 dispatcher 和 Platform 共享同一个 `AuroraRuntime`。

控制台可投递 AMP、强制推进周期、查询记录以及查看 scheduler/Episode 状态，但不得直接写 Kernel 记录或调用
Platform 私有 client。裸文本等价于 `/say`。当前基础命令为 `/help`、`/say`、`/event`、`/cycle`、`/record`、
`/status` 和 `/quit`；新增命令必须继续通过 localhost 业务用例维护边界。

## 验收标准

1. `uv run aurora console` 能通过 AMP/Kernel 用例完成消息投递、强制周期和记录查询。
2. `src.config.Config` 的公开字段来自同一份已校验 TOML 快照，不改变配置优先级。
3. 控制台和 scheduler 共享一个 Runtime/Kernel 所有者，退出时统一关闭 Platform 资源。
4. 控制台命令不会绕过 Kernel 记录或 Platform 效果执行。
