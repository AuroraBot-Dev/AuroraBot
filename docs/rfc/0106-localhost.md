# 0106：Localhost 运行组合

状态：已接受
日期：2026-07-23
来源：取代 RFC 0006、0007；整合自 RFC 0014、0020

## 职责

`src/localhost/` 是传输无关的应用与运行时层，提供 Console 与 Dashboard 共用的业务用例。
拥有命令路由、统一 ingress、模型 Activity 调度、工具分发、自主额度和调试接口。
声明供外部 Platform adapter 调用的窄公共端口。

## AuroraRuntime

`src.localhost.runtime.AuroraRuntime` 是唯一业务组合根。负责：

- 持有 `AgentKernel` 实例，调度 inbox 扫描和 pump
- 持有 model dispatcher（异步执行模型 Activity）
- 持有 tool dispatcher（领取并路由 tool Activity）
- 创建并注入 `PromptComposer`、Capability 列表、ToolExecutorBinding
- 公开 `route_input()`、`pump()`、`submit_amp()` 等 API

`aurora` 进程层只承担最外层构造、CLI 解析、平台选择、日志 bootstrap 和关闭序列。

## 统一输入路由

首个非空字符为 `/` 的文本经 shlex 分词和公共命令 parser 调用确定性业务用例；
其他文本进入 `message.received` AMP。

Console 与 Dashboard 使用相同的 `RuntimeInput`、命令目录和 `CommandResult`。

## 命令系统

| 命令      | 功能                           |
| --------- | ------------------------------ |
| `/status` | 返回 Runtime、Task、Agent 状态 |
| `/pump N` | 推进 N 个 turn                 |
| `/say`    | 以文本创建 AMP/Task            |
| `/event`  | 提交自定义 AMP 事件            |
| `/task`   | 查询 Task 详情                 |
| `/agent`  | 查询 Agent 详情                |
| `/clear`  | 清除 Console 屏幕              |
| `/log`    | 控制终端日志开关和级别         |
| `/quit`   | 优雅停止进程                   |
| `/help`   | 显示命令列表                   |

Dashboard 处于单租户可信域，开放全部运行时命令。命令消息和结果进入聊天持久化。

## 效果与工具闭环

```
Kernel tool Activity
  → localhost tool dispatcher
  → 唯一匹配的已启用 Platform executor
  → ToolOutcome (succeeded / failed / unknown)
  → localhost 提交 tool.succeeded / tool.failed / tool.unknown 到 Kernel
  → Kernel 在后续 pump 恢复原 Agent
```

Platform 是唯一执行环境效果的一层；localhost 只负责领取、路由和持久化结果。
平台不得直接完成 Activity 或修改 Agent 状态。

## 自主额度

| 配置项                         | 说明                 |
| ------------------------------ | -------------------- |
| `autonomous_daily_model_calls` | 每日自主模型调用上限 |
| `autonomous_daily_tokens`      | 每日自主 token 上限  |

localhost 持久化并执行自主额度，不包含 tick 时间、interval 或 Task 结果退避状态。
自主 tick 的产生由 Clock MCP App 负责，localhost 只消费收到的 `system.tick`。

## 调试 API

| 端点                              | 说明                       |
| --------------------------------- | -------------------------- |
| `GET /healthz`                    | 运行时可用状态             |
| `POST /v1/debug/amp`              | 校验并投递 AMP             |
| `POST /v1/debug/pump`             | 推进有限 turn              |
| `GET /v1/debug/status`            | 运行时、pump、自主额度状态 |
| `GET /v1/debug/tasks/{task_id}`   | 已脱敏 Task 详情           |
| `GET /v1/debug/agents/{agent_id}` | 已脱敏 Agent 详情          |
| `GET /v1/debug/brain-context`     | 当前 BrainContext 投影     |

调试服务默认监听 `127.0.0.1`；生产 profile 不得暴露到非 loopback 地址。
仅用于开发和契约测试，不提供最终用户聊天语义或远程管理。

## 约束

- localhost 不得导入具体 `src.platform.*` 实现
- 不得持有平台私有地址或协议对象
- AMP 正文和 SOUL 内容不写入 INFO 日志
- 配置只在组合根显式加载一次
