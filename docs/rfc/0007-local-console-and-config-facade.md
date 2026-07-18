# RFC 0007：本地控制台与显式配置快照

状态：已接受
日期：2026-07-11
修订：2026-07-19

## 背景

开发者需要通过同一套本地业务用例投递 AMP、推进 Agent turn 并查询审计状态。配置必须来自同一份已校验
快照，同时不能通过模块导入产生隐式读取或目录写入。

## 决策

### 配置入口

`src.contracts.configuration.load_configuration()` 是公开配置入口，返回 RFC 0002 定义的不可变 `AuroraConfig`
快照。DTO 和纯校验位于叶子层 `contracts`；`localhost` 组合根显式加载一次并注入 AI、Platform、scheduler 与
Dashboard 用例。不得在 import-time 调用加载、reload、创建目录或初始化全局配置门面。

### 本地控制台

`src/localhost` 提供分层开发控制台：`registry` 声明命令、`commands` 执行业务用例、`shell` 负责交互。
它与 scheduler、模型 dispatcher 和 Platform 共享同一个 `AuroraRuntime`。

控制台可投递 AMP、通过 `/pump` 推进有限 ready turn，并查询 Task、Agent 与 scheduler 状态，但不得直接写
Kernel 记录或调用 Platform 私有 client。裸文本等价于 `/say`；新增命令必须继续通过 localhost 业务用例维护边界。

## 验收标准

1. `uv run aurora console` 能通过 AMP/Kernel 用例完成消息投递、强制周期和记录查询。
2. 配置 DTO 无 localhost 依赖，导入项目包不会隐式加载配置或创建运行目录。
3. 控制台和 scheduler 共享一个 Runtime/Kernel 所有者，退出时统一关闭 Platform 资源。
4. 控制台命令不会绕过 Kernel 记录或 Platform 效果执行。
