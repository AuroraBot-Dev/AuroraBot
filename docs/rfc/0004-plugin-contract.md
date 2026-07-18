# RFC 0004：扩展契约

状态：已接受
日期：2026-07-11
修订：2026-07-19

RFC 0012 取代本文的认知节点扩展条款：认知扩展现为 `agents.toml` 中声明的同构 Agent profile 和纯
`handle(context, message) -> AgentDecision` 实现。Platform adapter、原生应用、完整 MCP 工具名和显式启用条款继续有效。

## 目标

定义 Agent profile、平台适配器和原生应用三类扩展。它们可以安装在 `extensions/` 或独立 Python 包中，但安装不等于启用。

## 已确认决策

- Agent profile 必须声明统一实现、模型角色、提示词、所需能力、委派权限和允许创建的子 profile。
- Agent handler 只能读取 Kernel 提供的上下文并返回决策；不得直接写运行态或调用平台私有 Client。
- 平台适配器负责生态私有协议与 AMP 之间的归一化，以及已授权效果的执行。
- 原生应用可以实现 AMP-MCP；它们经 Platform 接入，不绕过 Platform 直接影响 Kernel。
- 每个 Agent profile、应用和适配器必须在 TOML 中显式启用；发现或安装不得自动加入运行时。
- MCP 效果能力使用完整工具名 `<package>.<tool>`。发现的工具必须属于 `apps.toml` 中声明的 package 和 allowlist；Platform 是唯一执行 `effect.requested` 的一层。
- 运行时 App 配置只来自 TOML；YAML manifest 不参与发现、启用或路由。
- 支持内建 stdio 与外部 HTTPS Streamable HTTP MCP。远程 Bearer token 仅由显式 `auth_env` 引用。
- 本地交互终端是内建应用 `org.aurora.console`。它以 `org.aurora.console.send_message` 请求文本输出；Platform 将工具结果交给 localhost 输出队列，交互 shell 在周期完成后呈现，Kernel 只保留请求与 AMP 回执。

## 扩展边界

- 第三方 Python 插件自动发现、entry point 组名和签名/来源验证不属于当前契约，须由后续 RFC 定义。

## 验收标准

1. Clock MCP 可由 Platform 发现完整工具名并执行 `org.aurora.clock.get_current_time`。
2. MCP 成功、失败和 Clock 触发通知均以新的 AMP 事实回到 Kernel。
3. 未声明 package、工具前缀、远程 HTTPS 或认证来源的 App 在启动前失败。
4. `org.aurora.console.send_message` 的成功调用在本地交互终端输出一次，并保留对应 `effect.succeeded` AMP。
