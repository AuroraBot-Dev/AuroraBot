---
order: 5
---

# MCP 适配

MCP App 向 Bot 提供外部工具和业务事件，通过 `apps.toml` 配置连接。

## 传输与协商

`src/aurora_bot/mcp` 使用 MCP Python SDK 2.x，首选协议修订版 `2026-07-28`。SDK 自动协商版本，适配器状态记录实际 negotiated version。支持本地 stdio 与 HTTPS Streamable HTTP；不支持 HTTP+SSE。

## 启动发现与冻结

每个启用 App 在 `timeout_seconds` 的统一截止时间内完成连接、协商和完整分页 `tools/list`。目录变化监听在首次列表请求前建立；分页期间目录变化会使结果作废，需在剩余时间内重新读取或终止启动。

工具资源使用 `<package>:tool/definition/<别名>`。合法原名直接使用，其他名称转换为确定性别名，并保留到服务器原名的映射。description 与 object JSON Schema 进入 `ToolDefinition`。空名称、非 object schema、重复资源 ID 或任一 App 启动失败，会使整体启动失败并逆序清理连接和子进程。

发现完成后，MCP、内建与注入工具合并为 `ToolRegistry`，再校验 Agent 的工具引用。运行中目录冻结；变化记录为 `mcp.catalog.changed`，并报告 `restart_required=true`。连接断开不自动重连，对应调用返回 unknown 或可明确判定的 failed。

## 环境与网络边界

stdio 子进程只获得 SDK 基础环境及 App 白名单中的环境变量；stdout 承载 MCP，stderr 用于诊断。远程地址和每一跳重定向必须为 HTTPS，且 URL 不含 userinfo 或 fragment。Bearer 凭据通过 `auth_env` 读取，不跨授权 origin 转发。工具效果不自动重试。

## Tool 契约扩展

工具契约扩展标识为 `org.aurorabot/tool-contract`。Client 与 Server 的 `capabilities.extensions` settings 均严格等于 `{"version": 1}` 时协商成功；否则 Host 不解释对应的 Tool / CallToolResult `_meta`。

工具默认 observe 和 publish App scope `<package>:world`。协商后，Tool `_meta["org.aurorabot/tool-contract"]` 的 `observe`、`publish` 可分别指定非空、无重复的 scope 模板列表；省略字段使用默认值。

模板只能引用 input schema 的顶层参数，例如 `org.aurora.qq:world/group/{group_id}`。发现阶段校验模板与参数声明；调用阶段只接受文本或整数替换值，并校验最终 scope。参数缺失、类型不符或 scope 非法时，在发送 `tools/call` 前返回 failed。解析后的范围使用统一的 `ScopedTool` 与世界前沿屏障。

协商后，无法确认真实效果的 Server 调用必须在 `CallToolResult._meta["org.aurorabot/tool-contract"]` 返回 `{"status": "unknown"}`。Host 优先保留该状态，不受 `isError` 影响；其他 `isError` 表示可确认未发生效果或已完整回滚的失败。Host 在请求可能送达后遇到超时、断线或无法分类的协议错误，也返回 unknown。发送前校验失败和明确的参数、方法拒绝返回 failed。

succeeded 结果优先序列化 `structuredContent`，否则合并文本 content block；failed 与 unknown 保留错误文本。消息只承载文本，图像、音频、embedded resource 和 resource link 等非文本结果返回不支持错误。

## 业务事件扩展

`apps.toml` 的 `event_mode` 控制事件接入：

| 值                    | 行为                                                                                |
| --------------------- | ----------------------------------------------------------------------------------- |
| `disabled`            | 禁用业务事件（默认）                                                                |
| `world_events`        | 使用 `org.aurorabot/world-events` 扩展，仅支持 stdio                                |
| `legacy_aurora_event` | 转换 `notifications/message` 中 `logger=aurora/event` 的通知，仅适用于握手式 Server |

`world_events` 要求双方 capability settings 严格等于 `{"version": 1}`，通知 method 为 `notifications/org.aurorabot/world-events/event`。协商完成前、版本不符或启动失败期间的通知拒绝接收。

事件载荷映射为 `EnvironmentEvent(event_id, source, scope, kind, occurred_at, summary, data)`。两种事件模式均校验稳定 ID、scope 和 kind，并拒绝伪造保留事件。通知只追加世界，由 Bot 的认知入口决定何时处理。

事件采用 best-effort 交付，没有确认或重放保证。稳定 ID 用于收到后的幂等提交，断线丢失的事件不自动补发。
