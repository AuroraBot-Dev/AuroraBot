# RFC 0009：常驻 Bot 循环入口

状态：已接受
日期：2026-07-15

## 背景

RFC 0006 与 RFC 0007 在最小闭环尚未具备主动节律时，暂时禁止根目录 `bot.py` 参与 vNext 运行。
RFC 0008 已定义常驻 scheduler、周期外模型 dispatcher、Platform 回执与共享 `AuroraRuntime`，现在需要一个
不依赖交互控制台或调试 HTTP API 的无头入口，使 vNext 可以作为 Bot 持续运行。

本 RFC 只取代 RFC 0006“旧 `bot.py` 不参与本地运行器”和 RFC 0007 验收标准第 3 条。两份 RFC 的其余
本地用例、控制台和调试 API 契约继续有效。

## 决策

根目录 `bot.py` 是 vNext 的常驻无头组合入口。`uv run python bot.py` 必须创建且只创建一个
`AuroraRuntime`，调用其 `run_forever()` 持续推进 inbox、Kernel 周期、模型 dispatcher、Platform 效果回执
与主动 scheduler，并在退出时调用 `shutdown()`。

`bot.py` 只负责进程生命周期和组合，不实现 Kernel、Node、Platform 或 localhost 业务逻辑，不读取
`legacy/`，也不创建第二套运行时。默认项目根目录是 `bot.py` 所在目录；`--root` 与 `--profile` 只选择
RFC 0002 已定义的配置加载上下文，不能覆盖 TOML 结构值。

入口不默认启动控制台或开发调试 HTTP API。收到受支持的终止信号或任务取消时，它必须停止循环、关闭
Platform 资源并退出。启动和停止可以写 INFO 日志，但不得记录 AMP 正文、SOUL、用户内容、密钥或完整
模型提示词。

## 约束与非目标

- `src.localhost.runtime.AuroraRuntime` 仍是唯一组合根；`bot.py` 不成为可被 Node 调用的服务层。
- 本 RFC 不定义守护进程、Windows Service、systemd、容器编排、热重载或自动重启。
- 本 RFC 不把调试 HTTP API 提升为面向最终用户的远程 API。

## 验收标准

1. `uv run python bot.py` 能进入 `AuroraRuntime.run_forever()`，无需控制台输入或 HTTP 请求。
2. 入口把根目录与 profile 交给公开配置加载路径，且一个进程只创建一个 Runtime/Kernel 所有者。
3. 循环正常停止或被取消后始终调用 Runtime shutdown；入口生命周期具备自动化测试。

## 迁移影响

根目录原有的空文件或冻结入口语义被移除。`uv run aurora` 继续提供开发用 console + serve 组合入口；部署
或长期无头运行改用 `uv run python bot.py`。
