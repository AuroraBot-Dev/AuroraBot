<p align="center"><img src="assets/logo.svg" width="112" alt="AuroraBot Logo" /></p>

# AuroraBot

AuroraBot 是以树形同构 Agent 为核心的自主智能体框架。一组 Agent 通过消息、工具调用和委派共同完成一次运行。

一次运行就是一棵 `AgentTree`；root 与 child 共用同一种循环，
节点只因 system profile、初始 message、可见 tools 和使用的 LLM model 不同。

## 当前实现

```text
message → model → assistant
                  ├── Tool call → tool result → model
                  └── delegate → child Agent → tool result → parent
```

- 四个领域 role：`system / message / assistant / tool`；
- 节点级 model 与 Tool 可见性；
- 确定性的深度优先 AgentTree 循环；
- `runtime / engine / prompt` TOML 经显式注册合并为 `AuroraConfig`；
- 每个需实例化的 `src` 子包通过独立 composition 模块接入组合根；
- OpenAI-compatible `message → user` 纯适配；
- 全离线 fake Model/Tool 测试。

当前范围不包含数据库、恢复、自动记忆、Triage、MCP、Panel backend、sandbox 或生产化扩展体系。

## 开发

需要 Python 3.12 和 uv：

```bash
uv sync
uv run aurora check
uv run aurora about
uv run aurora donk show
```

`aurora check` 支持分别运行 lint 或测试，并可请求 Ruff 修复；`aurora donk show/major/minor/patch` 管理项目版本号。

项目不内置联网 Model。应用通过 `aurora.assemble_runtime(configuration, model, tools)` 注入具体 Model 和 Tool；这样 Provider
选择不会进入核心循环。

架构以 [RFC 0300](docs/rfc/0300-unified-architecture-and-contracts.md) 为准，实施结构见 [ARCHITECTURE.md](ARCHITECTURE.md)。
