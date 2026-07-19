<p align="center">
  <img src="assets/logo.svg" width="112" alt="AuroraBot Logo" />
</p>

<h1 align="center">AuroraBot</h1>

<p align="center">
  <b>中文</b> | <a href="README.en.md">English</a> | <a href="README.ja.md">日本語</a>
</p>

<p align="center">
  <em>拥有主动节律，能够持续工作，也能为每次行动说明来路的自主智能体框架。</em>
</p>

<p align="center">因果事件 · 同构 Agent · 主动节律</p>

<p align="center">
  <a href="https://github.com/AuroraBot-Dev/AuroraBot"><img src="https://img.shields.io/badge/GitHub-AuroraBot-181717?logo=github" alt="GitHub" /></a>
  <a href="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml"><img src="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-315b7d" alt="Apache 2.0" /></a>
  <img src="https://img.shields.io/badge/Python-3.12-315b7d?logo=python&logoColor=white" alt="Python 3.12" />
</p>

## 她是什么

AuroraBot 是一个面向开发者的开源自主智能体框架。她不把智能体理解成一次次互不相干的问答，而是让环境变化、
模型思考、能力调用和行动结果共同组成一段可以继续、可以暂停、也可以回看的经历。

当没有人说话时，AuroraBot 仍能按照自己的节律醒来，判断此刻是否值得行动；当任务变复杂时，她可以把工作交给
多个同构 Agent 协作完成；当她需要向外部世界做事时，只有经过声明和授权的能力才能真正产生效果。

> 她不是在等待指令，而是在持续观察、自主决策、主动行动。

## 你可以用她做什么

- **构建会主动醒来的 Agent**：持久化 scheduler 在预算内产生自主时刻，外部消息到来时又会立即让路给交互任务。
- **让复杂任务自然分工**：一个 Agent 可以直接处理简单请求，也可以有界地委派子任务，并在结果返回后继续工作。
- **把现实能力接进来**：通过 MCP 应用提供时间、提醒或其他工具；能力在使用前会经过授权与参数校验。
- **从不同入口与她相遇**：使用本地 Console 对话，连接独立 Dashboard 前端，或以 headless 方式嵌入自己的环境。
- **理解她为什么这样做**：输入、模型调用、工具请求、执行回执和终止原因都保留在同一条因果记录中。

仓库目前内建 Clock MCP 应用，可查询时间、设置闹钟和倒计时。它既是可用能力，也是接入新应用的最小示例。

## 一次真实的旅程

如果你说“晚上七点提醒我开会”，AuroraBot 不会把一段模型文本假装成已经完成的行动：

1. 你的消息成为一个环境事件，并唤醒独立任务。
2. 根 Agent 判断需求，选择已授权的 Clock 能力。
3. Clock 返回结构化回执，任务知道提醒确实已经建立。
4. 到点后，Clock 产生新的环境事件，再次唤醒 AuroraBot。
5. AuroraBot 通过当前平台把提醒真正送到你面前。

这条闭环也是 AuroraBot 与普通“指令 - 响应”封装的区别：模型负责判断，运行时负责让行动可靠发生。

## 快速开始

需要 Python 3.12、Git 和 [uv](https://docs.astral.sh/uv/)。当前最可靠的使用方式是从源码运行。

```powershell
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
Set-Location AuroraBot
uv sync --no-dev
Copy-Item .env.example .env

# 在 .env 中填写默认配置所需的 DEEPSEEK_API_KEY
uv run --no-dev --env-file .env aurora --console --mcp
```

启动后可以直接输入消息，使用 `/help` 查看命令，或用 `/status` 查看当前状态。

### 选择相遇方式

```powershell
# 使用 config/preference.toml：默认启动 Console、Dashboard 后端与 MCP
uv run --no-dev --env-file .env aurora

# 只启动本地 Console
uv run --no-dev --env-file .env aurora --console

# 不启动外部平台，仅运行 Kernel 与主动节律
uv run --no-dev --env-file .env aurora --headless
```

显式提供 `--console`、`--dashboard` 或 `--mcp` 时，它们共同组成精确的平台集合，不会与默认值叠加。
Dashboard 前端由独立项目提供，本仓库包含本地 Dashboard 后端和聊天桥接，不包含浏览器 UI。

## 让她成为你的 Agent

AuroraBot 把常见的定制入口保留在清晰的配置文件中：

| 想改变什么 | 从哪里开始 |
| --- | --- |
| 人格、语气与表达边界 | `config/prompts/SOUL.md` |
| 模型角色与 Provider | `config/aurora.toml` |
| 默认启动哪些平台 | `config/preference.toml` |
| Agent 的模型、能力与委派范围 | `config/agents.toml` |
| 接入本地或远程 MCP 应用 | `config/apps.toml` |

结构配置使用 TOML，密钥只从环境变量读取。扩展应用不需要直接接触 Kernel；可以先阅读
[扩展指南](extensions/README.md)和内建 [Clock 应用](src/apps/aurora-app-clock/README.md)。

## 当前阶段

AuroraBot 目前是 `0.4` 开发者预览，适合本地体验、框架研究和扩展开发。当前版本尚未提供内建长期记忆、
附件理解、Agent 沙箱工具或面向公网的多租户部署保证；运行中的 Dashboard 调试接口也只应留在本机边界内。

我们宁可清楚说明尚未完成的部分，也不把路线图写成已经存在的能力。当前公共行为以已接受 RFC 和测试为准。

## 继续阅读

- [贡献指南](docs/CONTRIBUTING.md)：搭建开发环境并提交改进
- [扩展 AuroraBot](extensions/README.md)：接入 MCP 应用与 Agent profile
- [模型网关](src/ai/README.md)：选择模型、能力与调用通道
- [RFC 阅读指南](docs/rfc/README.md)：理解当前有效的设计决策
- [日志规范](LOGGING.md)：调试信息、隐私与审计边界
- [社区行为准则](CODE_OF_CONDUCT.md)：共同维护友善的开源社区

## 开源

AuroraBot 使用 [Apache License 2.0](LICENSE) 开源。我们相信，好的智能体框架应该属于所有人。
