# Clock：让 AuroraBot 感知时间

Clock 是 AuroraBot 内建的 stdio MCP 应用。它让 Agent 能够查询当前时间、设置闹钟和倒计时，并在时间到达时主动产生
新的环境事件。除了直接使用，它也是开发 MCP 应用时最小、完整的参考。

包名：`org.aurora.clock`

## 可以做什么

| 工具 | 用途 | 主要参数 |
| --- | --- | --- |
| `org.aurora.clock.get_current_time` | 获取 UTC+8 当前时间 | `fmt`：`strftime` 格式 |
| `org.aurora.clock.set_alarm` | 设置一次性闹钟 | `time_str`：ISO-8601 或 `HH:MM`；`label` |
| `org.aurora.clock.set_timer` | 设置倒计时 | `seconds`；`label` |
| `org.aurora.clock.list_alarms` | 列出等待中的闹钟与计时器 | 无 |
| `org.aurora.clock.cancel_alarm` | 按 ID 取消任务 | `alarm_id` |

`HH:MM` 按 UTC+8 解释；如果当天时间已经过去，会安排到下一天。当前版本不解析“明天早上”一类自然语言，也不支持
重复闹钟。调用方应传入正数倒计时。

闹钟和计时器保存在 `data/app_data/org.aurora.clock/tasks.json`。应用重启后会恢复尚未到期的任务；到点时产生
`alarm.triggered` 或 `timer.triggered`，MCP Platform 再把它归一化成 AuroraBot 可以处理的 AMP 环境事件。

## 在 AuroraBot 中使用

根目录 `config/apps.toml` 已经声明 Clock 的启动命令和工具 allowlist，`config/agents.toml` 则把这些能力授予内建
Agent。启动 Console 与 MCP 后，可以直接用自然语言提出需求：

```powershell
uv run --env-file .env aurora --console --mcp
```

例如输入“十分钟后提醒我休息”。模型负责把需求转换成结构化工具参数，Clock 负责可靠计时，Platform 回执让 Agent
知道操作是否真正成功。

## 单独调试

```powershell
Set-Location src/apps/aurora-app-clock
uv run python mcp_server.py
```

stdio MCP Server 的 stdout 只用于 JSON-RPC，诊断日志写入 stderr。运行时发现的工具必须与 `config/apps.toml` 中的
allowlist 完全一致，否则 AuroraBot 会拒绝启动这项应用，避免能力配置与实际实现悄悄漂移。
