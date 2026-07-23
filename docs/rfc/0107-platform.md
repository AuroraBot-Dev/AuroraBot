# 0107：Platform 适配层

状态：已接受
日期：2026-07-23
来源：取代 RFC 0014、0017、0018、0020；整合自 RFC 0004

## 职责

Platform 是薄适配层，只拥有以下职责：

- 管理自身协议、连接、生命周期和私有资源
- 把外部事件归一化为 AMP
- 注册当前可用的 Tool descriptor 与唯一 executor
- 执行已授权 Tool request 并返回结构化 outcome
- 可选实现幂等账本、恢复、防回流、缓存或目标解析

Platform 不得：

- 把 App 或 Tool 按通信、utility、effect、publication 等分类
- 替 Agent 隐藏或过滤工具
- 规定 Agent 应在哪个平台回复
- 要求第三方 MCP Server 实现 Aurora 私有 schema

## 三个平台

| 包                       | 职责                                                |
| ------------------------ | --------------------------------------------------- |
| `src.platform.console`   | stdin shell、终端输出、Console Tool                 |
| `src.platform.dashboard` | HTTP/WebSocket、鉴权、聊天持久化、Dashboard Tool    |
| `src.platform.mcp`       | stdio/Streamable HTTP、连接管理、能力发现、MCP Tool |

三个平台共享无平台语义的轻量契约，但不得通过继承体系合并私有生命周期或协议对象。

## Tool 注册

每个启用的 Platform 在启动时向 localhost 注册 ToolExecutorBinding：

```text
descriptor             # ToolDescriptor (id, description, parameters_schema)
executor               # 实现 execute(request) -> ToolOutcome 的可调用对象
executor_source        # "platform.console" | "platform.dashboard" | "platform.mcp"
source_instance        # 平台实例标识
```

### 内建 Tool

- `org.aurora.console.send` — 文本写入本地 Console
- `org.aurora.dashboard.send` — 文本持久化并推送给 Dashboard owner

两者都是单租户固定目标，不需要模型选择私有地址。

### MCP Tool

- MCPPlatform 启动时调用标准 `tools/list` 动态发现
- raw_name 映射为 `<configured-package>.<raw_name>`
- 调用时使用原始 raw_name；第三方 Server 无需知道 Aurora package
- `config/apps.toml` 中只声明连接与生命周期，不包含 tool allowlist 或 kind 字段

```toml
[[app]]
package = "com.tencent.qq"
enabled = true
transport = "stdio"
working_dir = "extensions/qq"
command = ["qq-mcp"]
timeout_seconds = 30
```

## ToolOutcome

统一三态结果：

| 状态        | 语义                         | 对 Agent 影响                                            |
| ----------- | ---------------------------- | -------------------------------------------------------- |
| `succeeded` | 执行明确成功                 | 恢复 Agent；若 `complete_task=true` 则结束 Task/子 Agent |
| `failed`    | 执行明确拒绝或失败           | 恢复 Agent，不自动重试                                   |
| `unknown`   | 调用可能已发生但结果不可确定 | 恢复 Agent，不自动重试                                   |

未实现恢复的 executor 遇到重启中的 PROCESSING Tool 返回 `unknown`；未实现幂等的 executor 不得被 Runtime 自动重放。

## Console

- 直接拥有 `org.aurora.console.send`，不启动 MCP 子进程
- 文本通过 localhost 输入端口进入，经统一命令路由
- `terminal_logs` 控制启动时的全局终端日志开关

## Dashboard

- 单 Owner 鉴权：`config/platforms.toml` 的 `[platform.dashboard.owner]` 声明稳定 username
- 首次启动在数据库同目录创建 `Token.txt`（随机高熵 bootstrap token）
- `POST /api/auth/login` 只接受 `{"token_login": "..."}`；服务端常量时间比较
- 签发随机 opaque bearer session token，SQLite 只保存摘要
- 联系人固定为内建 Bot；owner 可查询历史、同步消息、上传附件、发送文本或命令
- Bot 是不可登录的系统用户；owner 与 Bot 是 Dashboard 仅有的活跃身份

## MCP 与自主心跳

- 内建 `org.aurora.clock` 拥有 `start_heartbeat` 和 `sleep(seconds)` 工具
- MCPPlatform 发现 Clock 后调用 `start_heartbeat` 建立 heartbeat
- 到期时 Clock 发送 `system.tick` notification，经统一 AMP ingress 创建 autonomous Task
- 未启用 MCP 或 Clock 不可用时，不产生自主 tick
- Agent 通过 `sleep(seconds)` 显式表达节律选择；fallback heartbeat 保证持续运行

## 可选执行增强

Platform executor 可以透明实现：request ID 幂等、dispatch ledger、PROCESSING 恢复、
self-loop 抑制、速率限制、私有目标 alias。这些增强不得改变 ToolDescriptor 的通用形态，
不得成为第三方 MCP 工具进入 catalog 的必要条件。

## 约束

- 禁用平台不初始化数据库、不打开 socket、不创建子进程、不注册 Tool
- MCP notification 必须经 localhost external AMP ingress，不得直接持有 Kernel ingress
- 非 owner 不得伪造 Dashboard 本地输入
- 外部 AMP 或 MCP notification 不得伪造 `tool.*` 保留类型
- Platform 不直接修改 Kernel 或 Agent 状态
