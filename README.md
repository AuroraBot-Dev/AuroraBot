<p align="center"><img src="assets/logo.svg" width="112" alt="AuroraBot Logo" /></p>

# AuroraBot

AuroraBot 是以树形同构 Agent 为核心的自主智能体框架。一组 Agent 通过消息、工具调用和委派共同完成一次运行。

一次运行就是一棵 `AgentTree`；root 与 child 共用同一种循环，
节点从预定义 `AgentDefinition` 创建，并可因 Agent prompt、初始 message、可见 tools 和使用的 LLM model 不同。

## 当前实现

```text
message → model → assistant
                  ├── Tool call → tool result → model
                  └── aur.agent.delegate → child Agent → tool result → parent
```

- 四个领域 role：`system / message / assistant / tool`；
- 节点级 model 与 Tool 可见性；
- 可复用 Agent 定义目录；同一 prompt 可预定义不同 model、tools 与 child allowlist；
- `aur.*` 统一工具域、不可变工具目录与唯一执行路由；
- `aur.agent.delegate` 作为真实 Tool 产生显式树操作请求；
- 确定性的深度优先 AgentTree 循环；
- 完整项目 TOML 与 Markdown Prompt 经显式注册合并为 `AuroraConfig`；
- 每个需实例化的 `src` 子包通过独立 composition 模块接入组合根；
- 同一操作资源目录提供 method/path 与斜杠文本入口，用于 AgentTree 监测、新运行和限定配置改动；
- LiteLLM 统一模型网关与 OpenAI-compatible role、Tool 名称适配；
- `aurora start` 本地异步终端、`--headless` 和统一停止路径；
- 全离线 fake Model/Tool 测试。

当前范围不包含数据库、恢复、自动记忆、Triage、MCP、Panel backend、sandbox 或生产化扩展体系。

## 开发

需要 Python 3.12 和 uv：

```bash
uv sync
cp -r config.example config
uv run aurora check
uv run aurora start
uv run aurora about
uv run aurora config list
uv run aurora donk show
```

`config.example/` 是随源码发布的模板；复制出的 `config/` 是个人配置并由 Git 忽略。`aurora check` 支持分别运行 lint 或测试，
并可请求 Ruff 修复；`aurora config list/show` 只读查看个人配置；
`aurora donk show/major/minor/patch` 管理项目版本号。

`aurora start` 在加载任何配置和组件前读取项目根目录的 `.env`，且不覆盖进程已有环境变量；随后从 `models.toml`
构造 LiteLLM 模型网关，密钥只读取配置声明的环境变量。嵌入调用与测试仍可通过
`aurora.assemble_runtime(configuration, model, tools)` 显式注入 Model 和 Tool；Provider 选择不会进入核心循环。

架构以 [RFC 0300](docs/rfc/0300-unified-architecture-and-contracts.md) 为准，实施结构见 [ARCHITECTURE.md](ARCHITECTURE.md)。
