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
</p>

## 她是什么

AuroraBot 是一个面向开发者的开源自主智能体框架。我们想做的不是一个能力更多的聊天机器人，而是一个能够持续存在、形成自己的节律，并在环境中自主判断和行动的 Agent。

一次运行就是一棵 `AgentTree`：root 与 child 共用同一种确定性循环，节点从预定义 `AgentDefinition` 创建，因 prompt、初始 message、可见 tools 与 LLM model 不同而不同。

我们习惯称她为"她"。这不只是文案风格：AuroraBot 的目标不是制造一个随叫随到的工具人，而是为数字生命提供一套可以生活的运行环境。她可以有自己的人格、状态和边界，也可以在需要时与人和外部世界建立联系。

## 设计哲学

### 一个有自己生活的智能体

对话不是世界的全部。即使没有人发送消息，时间仍在流逝，应用仍会产生事件。主动节律（cadence）让 Agent 在预算和边界内自行判断是否需要思考或行动，而不是永远停在输入框后面。

### 平等看待环境变化

用户消息、时间变化、应用事件、子 Agent 结果和行动回执，本质上都是外部世界的变化。它们通过同一套事件入口（世界线）进入认知过程，不会因为来自用户，就自动变成不可质疑的最高指令。

"平等"不表示没有优先级。交互处理可以优先调度，权限与安全规则也始终有效；它强调的是 Agent 先理解发生了什么，再结合上下文决定回应、行动、委派或保持安静。

### 判断与行动分开

模型负责理解和决策，但普通模型文本不能直接改变环境。外部行动必须经过已声明的能力、参数校验与执行，结果再作为新事件回到 Agent。自主并不意味着不可控。

## 主要能力

```text
message → model → assistant
                  ├── Tool call → tool result → model
                  └── aur.agent.delegate → child Agent → tool result → parent
```

- **主动运行**：节律 cadence 让时间本身成为输入——即使没有消息，Agent 也会按节律被唤起，并自行判断是否需要行动；
- **同构协作**：root 与 child 共用同一种循环；`aur.agent.delegate` 以真实 Tool 委派子 Agent，复杂工作拆成一棵 AgentTree；
- **事件平权**：用户消息、时间流逝与应用事件通过同一世界线进入认知，跨 scope 的连续事件流与观察前沿让 Agent 始终与外界同步；
- **连接外部世界**：本地 Console、Panel 后端与 MCP SDK 2.x 客户端（stdio / HTTPS Streamable HTTP）把不同来源统一为事件；
- **内建记忆**：最近活动 scope 的最新提交经 PromptAssembler 注入 system，超长上下文确定性截断；
- **可替换模型**：LiteLLM 统一模型网关，角色与 Provider 由 TOML 配置，密钥只从环境变量读取；
- **可追溯行动**：输入、模型调用、工具请求与执行结果处于同一条因果记录（WorldJournal）；
- **人格与能力可配置**：SOUL、WORLD、Agent 提示词、模型角色与工具可见性各有清晰配置入口；
- **统一操作目录**：engine、world、ai、console、cadence、memory、MCP 等运行时能力提供一致的 method/path 与斜杠文本入口（ops）；
- **全离线测试**：fake Model/Tool 让测试确定、离线、无网络。

范围不包括 Panel 附件与 WebSocket、sandbox、通用扩展平台，以及 MCP sampling、elicitation、roots、Tasks 和非文本结果注入。

## 快速开始

需要 Python 3.12、Git 与 [uv](https://docs.astral.sh/uv/)：

```bash
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot
uv sync
cp -r config.example config
cp .env.example .env
uv run aurora start
```

`aurora start` 会读取项目根目录的 `.env`（在 `.env` 中填入默认模型所需密钥，如 `DEEPSEEK_API_KEY`），并从 `models.toml` 创建模型网关。启动后直接输入消息即可对话；输入 `/help` 查看操作，输入 `/exit` 停止。不想启动本地终端时加 `--headless`：

```bash
uv run aurora start --headless
```

## 定制与扩展

| 想改变什么                   | 从哪里开始                      |
| ---------------------------- | ------------------------------- |
| SOUL、世界与 Agent 提示词    | `config/prompts.toml`、`config/prompts/` |
| 模型角色与 Provider          | `config/models.toml`            |
| Agent 定义与委派范围         | `config/agents.toml`            |
| 引擎限制与树结构             | `config/engine.toml`、`config/runtime.toml` |
| 节律与记忆                   | `config/cadence.toml`、`config/memory.toml` |
| 本地或远程 MCP 应用          | `config/apps.toml`              |
| 日志与持久化目录             | `config/logging.toml`、`config/storage.toml` |

结构配置使用 TOML，密钥只从环境变量读取。

## 开发

`config.example/` 是随源码发布的模板；复制出的 `config/` 是个人配置并由 Git 忽略。常用命令：

```bash
uv run aurora check        # lint、类型与测试
uv run aurora about        # 了解 AuroraBot
uv run aurora config list  # 查看已注册配置
uv run aurora setup        # 完整引导：依赖、子模块与面板
```

架构以 [RFC 0300](docs/rfc/0300-unified-architecture-and-contracts.md) 为准，实施结构见
[架构文档](docs/architecture/index.md)。

## 文档

- [快速开始](docs/start/getting-started.md)
- [配置](docs/start/configuration.md)
- [架构总览](docs/architecture/index.md)
- [当前实现状态](docs/reference/nightly-status.md)
- [贡献指南](CONTRIBUTING.md)
- [社区行为准则](CODE_OF_CONDUCT.md)

## 开源致谢

AuroraBot 使用了许多优秀的开源项目：

| 项目 | 在 AuroraBot 中的用途 |
| ------------------------------------------------------- | ---------------------- |
| [LiteLLM](https://github.com/BerriAI/litellm)            | 模型 Provider 接入与调用基础设施 |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) | MCP 客户端与工具协议   |
| [FastAPI](https://github.com/fastapi/fastapi) / [Uvicorn](https://github.com/encode/uvicorn) | Panel 本地后端 |
| [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) / [Rich](https://github.com/Textualize/rich) | Console 与终端体验 |
| [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) / [aiosqlite](https://github.com/omnilib/aiosqlite) | WorldJournal 持久化 |

也感谢其他开源 Agent/Bot 项目对这个领域的探索。特别感谢 [MaiBot](https://github.com/MaiM-with-u/MaiBot)，其"数字生命"理念为 AuroraBot 的早期思考提供了重要启发。

## 许可证

本项目以 [Apache License 2.0](LICENSE) 协议开源。
