# RFC 0013：统一命令路由与 Aurora 进程入口

状态：已接受
日期：2026-07-19

## 背景

项目曾同时由根目录 `bot.py`、`scripts.cli` 与 `src.dashboard.cli` 解析进程参数，并且只有本地 Console 能识别
斜杠命令。Dashboard 会把 `/status` 等确定性指令当作模型输入，进程生命周期也存在多个所有者。

## 决策

顶层 `aurora` 包是唯一进程组合层和 CLI 入口。`aurora`/`aurora dev` 启动 Runtime、Dashboard 与 Console；
`run` 仅启动 Runtime，`serve` 启动 Runtime 与 Dashboard，`console` 启动 Runtime 与 Console，`check` 执行质量
检查。所有运行模式共享一个 stop event、一个 `AuroraRuntime` 和一条关闭路径。删除 `bot.py`、`scripts` 与
Dashboard 自有 CLI；Dashboard 应用工厂只接受注入的 Runtime。

`src.localhost` 拥有唯一运行时输入路由。首个非空字符为 `/` 的文本经一次 shlex 分词和公共命令 parser 后调用
确定性业务用例；其他文本进入 `message.received` AMP。Console 与 Dashboard 使用相同的 `RuntimeInput`、命令目录
和 `CommandResult`。除 `/say` 外，命令不创建 Agent Task。每个 canonical 命令在 `commands/` 中恰有一个同名文件，
别名不创建重复实现。

Dashboard 处于单租户可信人格域，开放全部运行时命令。命令消息和结果继续进入聊天室持久化；同一客户端 UUID
不得重复执行命令副作用。WebSocket 必须先返回 `message_ack` 再发布 Bot 命令结果。`/quit` 的结果送达后才设置共享
stop event，并优雅停止整个进程。

`/log [on|off] [--level LEVEL]` 只修改当前进程的终端 handler。关闭终端日志不关闭文件日志，文件级别始终来自
启动时的 TOML 快照；终端开关和级别不写回配置、不跨重启持久化，并同时作用于现有、未来 Aurora logger 与
Uvicorn 终端日志。

## 验收标准

1. 进程参数只解析一次，wheel 可从空目录执行 `aurora --help` 和 `python -m aurora --help`。
2. 四种运行组合各自只启动声明的 surface，并始终只有一个 Runtime 所有者。
3. Console 与 Dashboard 的同名斜杠命令产生相同业务结果，普通文本仍创建 AMP/Task。
4. Dashboard 命令先 ack、可审计且幂等；`/quit` 可远程优雅停机。
5. `/log off` 静默终端但不影响文件诊断记录。
