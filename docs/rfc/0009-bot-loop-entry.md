# RFC 0009：常驻 Bot 组合入口

状态：已接受
日期：2026-07-15
修订：2026-07-19（入口条款由 RFC 0013 取代）

## 背景

RFC 0008 定义常驻 scheduler、周期外模型 dispatcher、Platform 回执与共享 `AuroraRuntime`。项目需要一个
统一进程入口，持续推进认知闭环并按配置承载面向用户的本地 Dashboard。

RFC 0013 取代本文的具体文件入口和模式命名；本文保留单 Runtime 所有权与关闭边界。

## 决策

顶层 `aurora` 包是进程组合入口。每种模式必须创建且只创建一个 `AuroraRuntime`，持续推进 inbox、Kernel、模型
dispatcher、Platform 效果回执与主动 scheduler。`--root` 与 `--profile` 只选择 RFC 0002 定义的配置加载上下文，
不能覆盖 TOML 结构值。

收到受支持的终止信号或任务取消时，入口必须停止循环、关闭 Dashboard server 与 Platform 资源，并调用
`AuroraRuntime.shutdown()`。启动和停止可以写 INFO 日志，但不得记录 AMP 正文、SOUL、用户内容、密钥或完整
模型提示词。

具体 `dev`、`run`、`serve` 与 `console` 组合由 RFC 0013 定义，并复用相同的 Runtime 组合与关闭边界。

## 约束与非目标

- `src.localhost.runtime.AuroraRuntime` 是唯一业务组合根；`aurora` 只承担最外层进程组合。
- 本 RFC 不定义守护进程、Windows Service、systemd、容器编排、热重载或自动重启。
- Dashboard 固定为 loopback；本 RFC 不定义公网部署、TLS 或反向代理。

## 验收标准

1. `uv run aurora serve` 以单 Runtime 启动认知循环和 Dashboard，无需控制台输入。
2. `uv run aurora run` 只启动认知循环，不创建 HTTP server。
3. 入口把根目录与 profile 交给公开配置加载路径，且一个进程只创建一个 Runtime/Kernel 所有者。
4. 循环或 server 正常停止、失败或被取消后始终执行 Runtime shutdown。
