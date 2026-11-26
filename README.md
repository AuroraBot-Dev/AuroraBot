<p align="center">
  <img src=".github/assets/logo.svg" width="112" alt="AuroraBot Logo" />
</p>

<h1 align="center">AuroraBot</h1>

<p align="center">
  <b>中文</b> | <a href="README.en.md">English</a> | <a href="README.ja.md">日本語</a>
</p>

<p align="center">
  <em>让 Bot 过上自己的生活。</em>
</p>

<p align="center">
  <a href="https://github.com/AuroraBot-Dev/AuroraBot"><img src="https://img.shields.io/badge/GitHub-AuroraBot-181717?logo=github" alt="GitHub" /></a>
  <a href="docs/INDEX.md"><img src="https://img.shields.io/badge/Docs-repository-315b7d" alt="Documentation" /></a>
  <a href="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml"><img src="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-315b7d" alt="Apache 2.0" /></a>
  <img src="https://img.shields.io/badge/Python-3.12-315b7d?logo=python&logoColor=white" alt="Python 3.12" />
</p>

## AuroraBot 是什么

AuroraBot 是一个为 Agent 提供可以"生活"的运行环境的 Bot 框架。我们想做的不是一个工具一般的 Agent，而是一个能够持续存在、形成自己的节律，并在环境中自主判断和行动的 Bot。

她有自己的人格、状态，可以在需要时与人和外部世界建立联系, 在她的世界里, 所有的消息都有一个"媒介": 你发给她的消息通过交流入口送达，外部应用也可以把事件带进她的世界喔~

## 设计哲学

### 以 Bot 为中心设计一切

AuroraBot 把 Bot 当作世界的主体，而不是被调用的接口：她一直存在，拥有自己的人格、状态与边界，一切设计都围绕她的生活展开。这个原则落到架构上有三条：

- **她拥有世界，运行只是她的经历**：Bot 持有自己的世界、目标与记忆。一次认知运行只是她的一段经历；聊天、任务都是她生活中的一次经历，经历结束，她仍然存在。
- **一切输入都有媒介**：用户消息通过交流入口提交引导；应用事件和 MCP 上报通过世界来源接入，工具结果回到当前推理，计划唤醒由运行所有者接纳。启用主动节律后，她也可以根据世界变化决定是否介入。
- **她理解之后才决定**：世界事件和外部内容不会因为出现就自动成为最高指令。她先理解发生了什么，再决定回应、行动或继续观察；模型只负责理解与判断，外部行动必须经声明的 Tool 执行，结果回到推理上下文，启用行动证据后另行归档。

## 快速开始

### 1. 克隆本仓库

需要 Python 3.12+、Git 与 [uv](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot
uv sync --locked --all-packages
uv run --locked python examples/onboarding/main.py --init
```

初始化会在独立的 `build/onboarding` 中补齐安装配置助手所需文件，不调用模型或启动工具。

### 2. 填写必要配置

在 `build/onboarding/config/org.aurora.adapter/model/profiles.toml` 中填写模型的 `provider`、`model` 和必要的 `base_url`；在根目录 `.env` 中设置 `AURORA_MODEL_API_KEY`，`credential` 只填环境变量名。

### 3. 从终端启动

```bash
uv run --locked python examples/onboarding/main.py --text "请检查我的环境，告诉我首次启动 Aurora 还缺什么。"
```

助手处理这条消息后退出，真实对话会调用你配置的模型。连续对话、TUI 和 Panel 的连接方法见[首次启动指南](examples/START.md)，正式 Bot 的启动见[操作指南](docs/operations.md)。

## AIGC

本项目存在经由人工审核的由生成式模型辅助编写的代码.

## 参与贡献

见[参与 AuroraBot](.github/CONTRIBUTING.md)与[AuroraBot 文档](docs/INDEX.md), 提交贡献即表示你同意遵守项目的[社区行为准则](.github/CODE_OF_CONDUCT.md).

## 开源致谢

AuroraBot 的诞生离不开许多优秀的开源项目：

| 项目                                                                                                                   | 在 AuroraBot 中的用途            |
| ---------------------------------------------------------------------------------------------------------------------- | -------------------------------- |
| [LiteLLM](https://github.com/BerriAI/litellm)                                                                          | 模型 Provider 接入与调用基础设施 |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)                                                   | MCP 客户端与工具协议             |
| [OpenTUI](https://github.com/anomalyco/opentui) / [Rich](https://github.com/Textualize/rich) | TUI 与日志展示               |
| [Vue](https://github.com/vuejs/core) / [Vite](https://github.com/vitejs/vite)             | Panel 界面与构建              |

也感谢其他开源 Agent/Bot 项目对这个领域的探索。特别感谢 [MaiBot](https://github.com/MaiM-with-u/MaiBot)，其"数字生命"理念为 AuroraBot 的早期思考提供了重要启发。

## 许可证

本项目以 [Apache License 2.0](LICENSE) 协议开源。
