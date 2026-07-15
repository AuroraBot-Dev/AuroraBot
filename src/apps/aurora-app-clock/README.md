# Clock MCP 应用

包名：`org.aurora.clock`

Clock 是内建 stdio MCP 应用，经 Platform 能力目录接入 AuroraBot。启用状态、启动命令、工具 allowlist 与
`result_mode` 只由根目录 `config/apps.toml` 声明；所有 Clock 工具当前均为 `resume`，执行成功或失败后都会恢复
发起它的 Episode。

## 工具

| 完整工具名 | 参数 | 结果 |
| --- | --- | --- |
| `org.aurora.clock.get_current_time` | `fmt: str = "%Y-%m-%d %H:%M:%S"` | 格式化的本地时间字符串 |
| `org.aurora.clock.set_alarm` | `time_str: str`, `label: str = ""` | 闹钟 ID、触发时间与状态 |
| `org.aurora.clock.set_timer` | `seconds: int`, `label: str = ""` | 计时器 ID、触发时间与状态 |
| `org.aurora.clock.list_alarms` | 无 | 当前闹钟和计时器列表 |
| `org.aurora.clock.cancel_alarm` | `alarm_id: str` | 是否成功取消 |

`set_alarm` 的 `time_str` 使用 `HH:MM` 24 小时格式；`set_timer` 的 `seconds` 必须为正整数。闹钟和计时器触发时，
应用通过 MCP 日志通知发送 `org.aurora.clock.alarm_triggered` 或 `org.aurora.clock.timer_triggered`，Platform 将其
归一化为新的 AMP 环境事件。

## 本地启动

通常由 Platform 按 `config/apps.toml` 自动启动。单独调试 stdio server：

```powershell
Set-Location src/apps/aurora-app-clock
uv run python mcp_server.py
```

stdout 只用于 MCP JSON-RPC，诊断日志写入 stderr。能力发现结果必须与 TOML allowlist 完全一致，否则运行时启动失败。
