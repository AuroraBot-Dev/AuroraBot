---
order: 2
---

# 常见问题

## AuroraBot 支持哪些社交平台？

平台接入由 MCP App 提供。运行 `aurora config apps --init` 创建的配置包含 Aurora-QQ 与 Windows-MCP 示例，默认均未启用。使用时需要安装对应 App、配置凭据并启用连接；具体平台能力由 App 决定。

App 提供工具和业务事件，Bot 负责判断与行动。接入要求、传输支持和事件配置见 [MCP 应用接入](../architecture/mcp)。

## 修改配置后需要重启吗？

需要。配置、插件与工具目录在启动时加载，运行期间保持固定。使用 `aurora config --check` 校验配置后重新启动。

## 工具返回 unknown 是什么意思？

请求可能已产生效果，但无法确认结果。应先核对外部状态，避免重复执行。状态和恢复规则见[资源与操作](./resources-and-operations#结果与恢复)。
