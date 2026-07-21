# 扩展 AuroraBot

扩展 AuroraBot，意味着为她增加一种新的做事方式，或一种新的协作角色。当前版本提供两条明确的入口：

- **MCP 应用**把时间、文件、服务或设备等外部能力带进来。
- **Agent profile**定义一个 Agent 使用什么模型、拥有哪些能力，以及可以把工作交给谁。

`extensions/` 可以用来存放你自己的扩展源码，但放进这个目录并不代表自动安装或启用。AuroraBot 当前不扫描第三方
Python 插件；所有扩展都必须通过 TOML 显式声明，这让启动结果和能力边界保持可预测。

## 从一个 MCP 应用开始

MCP 应用最接近 AuroraBot 的“感知器与执行器”：它可以提供工具，也可以在环境发生变化时发回事件。

1. 实现一个 stdio 或 HTTPS Streamable HTTP MCP Server。
2. 在 `config/apps.toml` 中只声明 package、transport、连接或启动方式和超时。
3. MCP Server 通过标准 `tools/list` 暴露工具，无需在 AuroraBot 中维护工具 allowlist。
4. 在 `config/agents.toml` 中用精确 Tool ID、`package.*` 或 `*` 设置 Agent profile 的能力策略。
5. 使用 `uv run --env-file .env aurora --console --mcp` 启动并验证完整闭环。

内建 [Clock 应用](../src/apps/aurora-app-clock/README.md)展示了本地 stdio Server、工具发现、持久化任务和主动事件通知。

AuroraBot 会在启动时动态发现 Server 的全部工具，并以配置 package 为 raw tool name 添加前缀。第三方 App 不需要
Aurora 专用的 kind、tool、publication 或 destination 配置。模型只有在 Agent profile 的能力策略允许时才能请求工具；
参数仍按 Server 提供的 JSON Schema 校验，执行结果则作为统一工具回执交还原先等待的 Agent。

## 定义一个 Agent profile

Agent profile 在 `config/agents.toml` 中显式配置，包括：

- 唯一 `id` 和 handler implementation；
- 使用的模型角色；
- 能力策略；角色提示词由同 ID 的 `config/prompts.toml` 条目声明；
- 是否允许委派，以及允许创建哪些 child profile。

当前内建 profile 使用同一种 `ToolAgent` handler，通过不同模型和能力策略承担不同角色。新增 profile 不等于新增一种
绕过运行时的 Agent 类型；它仍然通过邮箱、Activity、预算和监督树参与同一个因果闭环。

## 扩展边界

- 不要直接读写 `data/kernel/`，也不要把 Provider 或平台 Client 对象放进 Agent 状态。
- 不要让模型普通文本直接触发环境效果；效果必须通过已声明的 Platform 能力执行。
- 不要依赖目录扫描、热加载、签名验证或第三方 Python Platform 自动发现；当前版本没有这些契约。
- 密钥只通过环境变量注入，结构和启用状态继续由 TOML 决定。

若扩展需要新的公共协议、Platform 类型或运行时边界，请先按 [RFC 流程](../docs/rfc/README.md)提出设计。
