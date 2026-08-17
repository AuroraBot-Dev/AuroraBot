<p align="center">
  <img src="assets/logo.svg" width="112" alt="AuroraBot Logo" />
</p>

<h1 align="center">AuroraBot</h1>

<p align="center">
  <b>中文</b> | <a href="README.en.md">English</a> | <a href="README.ja.md">日本語</a>
</p>

<p align="center">
  <em>让 Agent 拥有自己的生活。</em>
</p>

<p align="center">事件平权 · 同构协作 · 主动节律</p>

<p align="center">
  <a href="https://github.com/AuroraBot-Dev/AuroraBot"><img src="https://img.shields.io/badge/GitHub-AuroraBot-181717?logo=github" alt="GitHub" /></a>
  <a href="https://www.aurorabot.org/"><img src="https://img.shields.io/badge/Docs-aurorabot.org-315b7d" alt="Documentation" /></a>
  <a href="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml"><img src="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-315b7d" alt="Apache 2.0" /></a>
  <img src="https://img.shields.io/badge/Python-3.12-315b7d?logo=python&logoColor=white" alt="Python 3.12" />
  <img src="https://img.shields.io/badge/Nightly-0.6%20alpha-6f5b95" alt="Nightly 0.6 alpha" />
</p>

## 她是什么

AuroraBot 是一个面向开发者的开源自主智能体框架。我们想做的不是一个能力更多的聊天机器人，而是一个能够持续存在、形成自己的节律，并在环境中自主判断和行动的 Agent。

我们习惯称她为“她”。这不只是文案风格：AuroraBot 的目标不是制造一个随叫随到的工具人，而是为数字生命提供一套可以生活的运行环境。她可以有自己的人格、状态和边界，也可以在需要时与人和外部世界建立联系。

## 设计哲学

### 一个有自己生活的智能体

对 AuroraBot 来说，对话不是世界的全部。即使没有人发送消息，时间仍在流逝，应用仍会产生事件，尚未完成的工作仍可继续。主动节律让她能够在预算和边界内自行判断是否需要思考或行动，而不是永远停在输入框后面。

### 平等看待环境变化

用户消息、时间变化、应用事件、子 Agent 结果和行动回执，本质上都是外部世界发生的变化。它们通过同一套事件入口进入认知过程，不会因为来自用户，就自动变成不可质疑的最高指令。

“平等”不表示没有优先级。交互任务可以优先调度，权限与安全规则也始终有效；它强调的是 Agent 先理解发生了什么，再结合上下文决定回应、行动、委派或保持安静。

### 判断与行动分开

模型负责理解和决策，但普通模型文本不能直接改变环境。外部行动必须经过已声明的能力、参数校验和 Platform 执行，结果再作为新事件回到 Agent。这样，自主并不意味着不可控。

## 主要能力

- **主动运行**：启用内建 Clock MCP 后，可持久化自主心跳并产生受预算约束的自主任务；外部输入到来时及时切回交互工作。
- **持续任务**：任务可以异步等待模型、工具和子 Agent，在结果返回后恢复，并有明确的预算与终态。
- **多 Agent 协作**：同构 Agent 通过有界委派组成监督树，简单工作直接完成，复杂工作可以并行拆分。
- **会话持续演进**：revision、watermark、delta 与提交屏障让新事件能进入正在进行的会话，并隔离被取代的旧生成。
- **连接外部世界**：Console、本地 Panel 后端和 MCP Platform 将不同来源统一为事件，并提供经过授权的环境能力。
- **内建记忆**：短期窗口与概要、全局 durable facts、mem0/Chroma 语义检索组成可降级的长期记忆链路。
- **可替换模型**：fast、quality、multimodal、embedding 角色与 Provider 由 TOML 配置；当前对话调用统一使用 Chat Completions 语义。
- **可追溯行动**：输入、模型调用、能力请求、执行结果和终止原因处于同一条因果记录中。
- **人格与能力可配置**：SOUL、Agent profile、模型角色、平台组合和 MCP 应用各自拥有清晰配置入口。

## 快速开始

需要 Python 3.12（推荐，以上版本未经充分验证）、Git 和 [uv](https://docs.astral.sh/uv/)。当前推荐从源码运行。

```powershell
git clone --branch nightly --single-branch https://github.com/AuroraBot-Dev/AuroraBot.git
Set-Location AuroraBot
uv sync --no-dev
Copy-Item .env.example .env
```

在 `.env` 中填写默认模型所需的 `DEEPSEEK_API_KEY`。当前 `config/apps.toml` 默认启用仓库外的
`org.aurora.qq` 扩展；如果没有安装 `extensions/apps/Aurora-QQ`，请先在对应 `[[app]]` 中设为
`enabled = false`，否则启动会按严格配置规则失败。

```powershell
uv run --no-dev --env-file .env aurora start
```

启动后可直接输入消息，使用 `/help` 查看命令，或用 `/engine/status` 查看运行状态。

```powershell
# 使用 config/platforms.toml 中的默认平台组合
uv run --no-dev --env-file .env aurora start

# 无头模式：不启动本地 Console，平台组合不变
uv run --no-dev --env-file .env aurora start --headless
```

本地 Console 不随 `--platform` 选择启停：只要不是无头模式且 `[runtime.console].enabled = true`，它就会运行。

显式提供 `--platform` 时，这些平台组成精确的平台集合，不与默认值叠加。完整浏览器前端由独立的
[AuroraBot Panel](https://github.com/AuroraBot-Dev/AuroraBot-panel) 项目提供；本仓库只包含 loopback、本地单 owner 的后端与聊天桥接。

## 定制与扩展

| 想改变什么                    | 从哪里开始              |
| ----------------------------- | ----------------------- |
| SOUL、世界说明与 Agent 提示词 | `config/prompts.toml`   |
| 模型角色与 Provider           | `config/models.toml`    |
| engine 限制与 Task 预算       | `config/engine.toml`    |
| 持久化目录                    | `config/storage.toml`   |
| 默认启动的平台                | `config/platforms.toml` |
| Agent 的模型、能力与委派范围  | `config/agents.toml`    |
| 本地或远程 MCP 应用           | `config/apps.toml`      |

结构配置使用 TOML，密钥只从环境变量读取。扩展可以从[扩展指南](extensions/README.md)和内建
[Clock 应用源码](src/apps/aurora-app-clock/mcp_server.py)开始。

## 当前阶段

AuroraBot `0.6 alpha`（`nightly`）适合本地体验、运行时研究和扩展开发。当前附件只完成存储与引用传递，尚未形成完整多模态理解链路；七端口贡献模型尚在收口统一生命周期与装配快照；sandbox 尚未接入授权运行时；MCP 断线自动恢复、终态数据 TTL、一致备份，以及面向公网的多租户部署保证也不在当前承诺内。公共行为以 [RFC 0300](docs/rfc/0300-unified-architecture-and-contracts.md)、契约与测试为准。

## 文档

- [快速开始](https://www.aurorabot.org/start/getting-started)
- [Nightly 当前状态与边界](https://www.aurorabot.org/reference/nightly-status)
- [系统架构](ARCHITECTURE.md)与[技术说明](TECHNICAL.md)
- [贡献指南](CONTRIBUTING.md)
- [扩展 AuroraBot](extensions/README.md)
- [RFC 阅读指南](docs/rfc/index.md)
- [演化路线图](ROADMAP.md)
- [日志规范](LOGGING.md)
- [社区行为准则](CODE_OF_CONDUCT.md)

## 开源致谢

AuroraBot 使用了许多优秀的开源项目：

| 项目                                                                                                                   | 在 AuroraBot 中的用途            |
| ---------------------------------------------------------------------------------------------------------------------- | -------------------------------- |
| [LiteLLM](https://github.com/BerriAI/litellm)                                                                          | 模型 Provider 接入与调用基础设施 |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)                                                   | MCP 应用和工具协议               |
| [FastAPI](https://github.com/fastapi/fastapi) / [Uvicorn](https://github.com/encode/uvicorn)                           | Panel 本地后端                    |
| [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) / [Rich](https://github.com/Textualize/rich) | Console 与终端体验               |
| [jsonschema](https://github.com/python-jsonschema/jsonschema)                                                          | 能力参数校验                     |

也感谢其他开源 Agent/Bot 项目对这个领域的探索。特别感谢 [MaiBot](https://github.com/MaiM-with-u/MaiBot)，其“数字生命”理念为 AuroraBot 的早期思考提供了重要启发。

## 许可证

本项目以 [Apache License 2.0](LICENSE) 协议开源。
