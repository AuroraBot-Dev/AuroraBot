---
order: 5
---

# MCP 适配

本页描述现行 MCP 适配实现。设计思想见 `RFC 0300`；协议精确词汇见 `reference/`。

## 传输与协商

`src/aurorabot/mcp` 是 MCP Python SDK 2.x 的客户端适配包，依赖 `mcp>=2,<3`，首选协议修订版 `2026-07-28`。客户端使用 SDK v2 的自动协商模式：现代 Server 使用 `server/discover` 与无会话语义，旧 Server 可由同一 SDK 显式协商回退到早期修订版。适配器必须在状态中暴露实际 negotiated version；不允许通过 TOML 选择 SDK v1 实现或伪装协议版本。支持本地 stdio 与 HTTPS Streamable HTTP，不新建旧 HTTP+SSE 连接。

## 启动发现与冻结

每个启用 App 在启动阶段完成连接、协议协商与完整分页 `tools/list`；从建立传输、握手到全部页面读取完成的整个启动事务必须受该 App 的 `timeout_seconds` 单一截止时间约束，不能只给单次 `tools/call` 设置超时。目录变化监听必须在首次 `tools/list` 之前建立，且同一协议通知只能由一个权威接收路径处理。监听到启动中的目录变化时，本次分页结果作废；实现可以在剩余截止时间内重新完整分页，也可以使启动失败，但不得冻结已经知道过期的目录。raw tool name 与配置 package 组合为 `<package>:tool/definition/<别名>`。package 是资源命名空间；合法原始名称直接接纳，其他第三方名称经确定性别名进入资源路径，执行器冻结到服务器原名的反向映射。第三方 Server 无需改名，领域资源名与 Provider function name 也保持分离。description 与 object JSON Schema 进入 `ToolDefinition`。空名称、非 object schema、重复领域 ID 或任一启用 App 启动失败，都使整体启动失败并逆序回收已建立的连接和子进程。

全部发现完成后，MCP Tool 与 builtin/外部注入 Tool 才合并为最终 ToolRegistry，随后校验 AgentDefinition 的精确 Tool ID 引用。运行中不热替换目录；`tools/list_changed` 或重发现差异只记录 `mcp.catalog.changed` 并报告 `restart_required=true`，不能替换 ToolRegistry 或改写已有 AgentNode。启动后连接断开不自动重连；目录保持冻结，对应调用返回 unknown 或可明确判定的 failed。

## 环境与网络边界

stdio 子进程只获得 SDK 安全基础环境与 App 配置显式白名单中的环境变量；stdout 只承载 MCP，诊断通过 stderr 进入日志。远程地址及每一跳重定向目标都必须为 HTTPS；任何向明文 HTTP 的降级重定向都必须在发送后续请求前拒绝。重定向目标仍须通过无 userinfo、无 fragment 的 URL 校验，Bearer 凭据只按 `auth_env` 从进程环境读取且不得跨授权 origin 转发。适配器不包装 SDK 私有接收方法，不手写 stdio JSON-RPC 转发，不自动重试工具效果。

## Tool 契约扩展

Aurora MCP Tool 的版本化契约扩展标识为 `org.aurorabot/tool-contract`。Client 与 Server 只有在各自 `capabilities.extensions` 中都提供内容严格等于 `{"version": 1}` 的 settings 时才协商成功；缺少字段、版本类型或数值不符、出现额外字段都视为未协商。未协商时 namespaced Tool / CallToolResult `_meta` 不得产生语义，Server 也不得依赖 Host 解释它们。

每个 MCP Tool 默认同时 observe 与 publish App scope `<package>:world`。协商 v1 后，Tool `_meta["org.aurorabot/tool-contract"]` 可以用 `observe` 和 `publish` 分别声明非空、无重复的 scope 模板列表；某一字段省略时，该字段仍使用 App scope 默认值。模板只允许引用 object input schema 中的顶层参数，例如 `org.aurora.qq:world/group/{group_id}`；不允许点路径、数组下标、默认值、转换函数或嵌套对象取值。发现时必须验证元数据形状、占位符语法及其引用的顶层 property；固定模板还须在发现时成为合法 scope。调用前只允许用本次 arguments 中的文本或整数标量替换占位符，并再次校验最终 scope。缺失参数、布尔值、对象、数组或替换后的非法 scope 都在发送 `tools/call` 前返回 failed，因此不会产生远端效果。解析出的 observe / publish scope 进入普通 `ScopedTool` 与 engine frontier 屏障，不形成 MCP 专用授权或因果通道。

协商 v1 后，Server 对请求可能已经送达或开始执行、但真实效果因内部超时、下游断线或其他原因无法确认的调用，必须在 `CallToolResult._meta["org.aurorabot/tool-contract"]` 中返回严格对象 `{"status": "unknown"}`。Host 必须优先保留为 `ToolOutput.unknown`，无论该结果的 `isError` 为何，不得降格或自动重试。明确的参数/方法拒绝，以及 Server 能确认效果没有发生或已经完整回滚的错误，才可以返回 failed；协商 v1 的 Server 返回其他 `isError`，即声明该错误没有不确定副作用。Host 自身在请求可能送达后遇到的超时、断线或无法分类的协议错误同样映射为 unknown；只有发送前本地校验和明确的参数/方法拒绝映射为 failed。

MCP succeeded 结果优先把 `structuredContent` 确定性序列化为文本，否则合并文本 content block；failed 与 unknown 均保留面向模型的错误文本。当前四角色消息只承载文本，因此图像、音频、embedded resource、resource link 与其他非文本结果不得静默丢失或将原始二进制塞入 transcript；适配器必须返回明确的不支持错误，扩展结果类型需要先定义明确内容契约与测试。

## 业务事件扩展

现代 MCP App 的业务事件使用版本化扩展 `org.aurorabot/world-events`，不使用已弃用的协议 logging 作为新设计。扩展通知 method 固定为 `notifications/org.aurorabot/world-events/event`。Client 与 Server 的 capability settings 都必须严格等于 `{"version": 1}`，且 App 配置必须显式启用；Host 在握手完成并验证双方 settings 前不得把该通知写入 World，未协商、版本不符或启动失败期间收到的通知必须拒绝。载荷映射为 `EnvironmentEvent(event_id, source, scope, kind, occurred_at, summary, data)`。无稳定 event id、非法 scope/kind 或伪造保留事件的载荷必须拒绝；普通未协商 vendor notification 不自动成为业务事实。为迁移已有旧 Server，`apps.toml` 可对单个 App 显式开启受限的 legacy `notifications/message + logger=aurora/event` 转换；该兼容路径必须使用同样的载荷验证和世界提交边界，不得成为通用日志入口。当前 Streamable HTTP 客户端没有为自定义扩展建立可持续的 Server→Client 事件订阅，因此该 transport 与 `world_events` 的组合必须在启动效果前拒绝；不能把一次请求期间可用的响应流当成长连接。事件通知是 best-effort：协议没有 Aurora 级确认、重放或送达证明，稳定 event id 只用于收到后的幂等提交；Server 只能报告通知尝试或 Host 已实际提交的事件，不能把“已发送”表述为“已送达”。断线期间丢失的事件不创建恢复队列，也不直接唤起 AgentTree。

当前不建立旧工具活动、异步回执、AMP、恢复队列、动态重绑定、通用生命周期或多级 catalog。MCP 包内封闭的连接/关闭不是通用扩展生命周期。将来若真实异步工具需要更多语义，必须继续让模型只看到同一个工具 ID/definition 目录，并保持 Tool call 到一次规范化 tool 消息的对应关系。
