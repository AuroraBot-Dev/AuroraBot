<p align="center">
  <img src="assets/logo.svg" width="112" alt="AuroraBot Logo" />
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
  <a href="https://www.aurorabot.org/"><img src="https://img.shields.io/badge/Docs-aurorabot.org-315b7d" alt="Documentation" /></a>
  <a href="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml"><img src="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-315b7d" alt="Apache 2.0" /></a>
  <img src="https://img.shields.io/badge/Python-3.12-315b7d?logo=python&logoColor=white" alt="Python 3.12" />
</p>

## AuroraBot 是什么

AuroraBot 是一个为 Agent 提供可以"生活"的运行环境的 Bot 框架。我们想做的不是一个工具一般的 Agent，而是一个能够持续存在、形成自己的节律，并在环境中自主判断和行动的 Bot。

她有自己的人格、状态，可以在需要时与人和外部世界建立联系, 在她的世界里, 所有的消息都有一个"媒介": 你发给她的消息也必须先成为一个应用通知喔~

## 设计哲学

### 以 Bot 为中心设计一切

AuroraBot 把 Bot 当作世界的主体，而不是被调用的接口：她一直存在，拥有自己的人格、状态与边界，一切设计都围绕她的生活展开。这个原则落到架构上有三条：

- **她拥有世界，树只是她的运行**：Bot 持有追加式的世界提交（WorldJournal）与多棵 `AgentTree`。一棵树只是一次运行，不是与她平行的另一个主体；聊天、任务、委派都是她生活中的一次经历，经历结束，她仍然存在。
- **一切输入都有媒介**：任何影响她的变化都必须先成为一条世界事件。你发给她的消息要先作为 `console.input` 提交到她的世界，应用事件、MCP 上报、工具结果、时间的流逝也是如此。她不是在响应接口，而是在经历世界。
- **她理解之后才决定**：来自用户的消息不会因为来源就自动成为最高指令。她先理解发生了什么，再决定回应、行动、委派或保持安静；模型只负责理解与判断，外部行动必须经声明的 Tool 执行，结果再作为新事件回到她的世界。

### 持续状态与自主安排

`config/bot.toml` 指定长期稳定的 Bot 身份。目标、完成条件、恢复检查点和未来活动安排属于这个身份，保存在世界日志中，进程重启后可以恢复。

Bot 可以通过 `bot_state` 读取自己的状态，通过 `goal_set` 建立、修订、暂缓或结束目标，通过 `wake_schedule` 安排一次带时区的未来检查，通过 `wake_cancel` 取消尚未开始的安排。修改需要携带读取到的状态版本，避免覆盖新的选择。

时间服务持续兑现已经登记的安排；这些安排不受事件批量节律开关影响。重启时，已经开始但没有完成记录的认知会被标记为中断，保留待核对的行动依据。恢复过程不会自动重放这些行动。

每次认知都显式获得主体状态。上下文组装保留原始输入、最新完整交互和恢复依据，候选经历按剩余容量进入；必要状态超限会明确报错，需要拆分工作或调整容量。

### 资源与领域操作

资源使用 `namespace:domain/kind/path` 寻址，例如 `aurora:bot/query/state`。定义版本、可变别名和 Bot 的运行实例分别记录。存在多个版本时，调用方需要明确选择版本或绑定别名；进行能力替换时可以校验契约身份与版本。

模组声明命令或查询的定义、参数结构、世界域和处理者。统一路由在执行前记录请求与确定版本，结果再次进入世界；重复请求复用持久回执。命令已经开始但结果未确认时，只有声明可安全重试的处理者可以再次执行。

结构化工具和终端指令共用这些定义。终端可使用：

```text
/resources --domain bot --kind command
/inspect aurora:bot/command/goal_set@1
/call aurora:bot/query/state {}
```

扩展通过 `OPERATION_CONTRIBUTIONS` 提供领域操作，通过 `RESOURCE_CONTRIBUTIONS` 提供其他资源定义，通过 `RESOURCE_ALIASES` 声明版本绑定。为操作填写 `tool_name` 后，框架会生成模型工具入口；Bot 的可见工具仍由 Agent 定义选择。

### 节律判断与训练

`cadence.toml` 控制世界消费入口、Agent 和检查频率，`rhythm.toml` 选择节律策略。规则基线按事件压力、即时路由和最长安静时间提供推理机会；GRU 模型使用相同的观察特征，并同时预测是否思考与下次检查时长。每次等待或唤醒都会记录策略版本、有效参数、观察、循环隐状态和后续运行结果。重启后恢复消费游标与等待安排，已经开始且结果未知的认知不会自动重放。

训练依赖通过 `uv sync --extra learning` 安装；开发依赖组也包含训练环境。基础运行可以只安装非开发依赖并选择规则策略。模型使用 [PyTorch GRU](https://docs.pytorch.org/docs/stable/generated/torch.nn.GRU.html)，不要求 CUDA。

```text
/call aurora:rhythm/query/observations {"after":0,"limit":100}
aurora train rhythm train.jsonl validation.jsonl models/rhythm.pt
```

观察查询返回原始决策输入与实际选择，供标注和可回放实验使用，不自动生成“正确”标签。训练数据每行是一段经历，包含 `schema_version = 1`、`episode_id` 和 `examples`；每个样本分别记录 `observation`、`think_value`、`wait_value`、`next_check_seconds`。效用需要由任务结果、独立标注或受控回放提供，监督目标是思考相对等待的增量价值。验证经历必须独立且晚于训练经历，报告同时列出学习模型和规则基线的误差与效用遗憾。

使用导出的权重时，在 `rhythm.toml` 中指定 `policy = "aurora:rhythm/model/gru"` 和 `weights = "models/rhythm.pt"`。权重按内容生成版本；权重或推理参数变化后，节律会保留消费位置并清空不兼容的循环状态。训练命令不会自动启用新权重。

## 快速开始

### 1. 克隆本仓库

需要 Python 3.12、Git 与 [uv](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot
./scripts/linux/setup.sh
# macOS: ./scripts/macos/setup.command;
# Windows: .\scripts\windows\setup.ps1.
```

`setup.sh` 会检查 git/uv/pnpm，询问是否将 aurora 全局链接到用户工具目录，然后由 `aurora setup` 完成依赖同步、个人配置以及 docs/panel 子模块引导。

### 2. 填写必要配置

在 `.env` 中填入默认模型所需密钥（如 `DEEPSEEK_API_KEY`）

### 3. 从终端启动

```bash
aurora start
```

启动后直接输入消息即可对话；输入 `/help` 查看操作，输入 `/exit` 停止。

## AIGC

本项目存在由大语言模型或扩散模型等生成式模型辅助编写的代码, 并经由人工审核.

## 参与贡献

见[参与 AuroraBot](CONTRIBUTING.md)与[AuroraBot 文档站](https://www.aurorabot.org), 提交贡献即表示你同意遵守项目的[社区行为准则](CODE_OF_CONDUCT.md).

## 开源致谢

AuroraBot 的诞生离不开许多优秀的开源项目：

| 项目                                                                                                                   | 在 AuroraBot 中的用途            |
| ---------------------------------------------------------------------------------------------------------------------- | -------------------------------- |
| [LiteLLM](https://github.com/BerriAI/litellm)                                                                          | 模型 Provider 接入与调用基础设施 |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)                                                   | MCP 客户端与工具协议             |
| [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) / [Rich](https://github.com/Textualize/rich) | Console 与终端体验               |
| [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) / [aiosqlite](https://github.com/omnilib/aiosqlite)             | WorldJournal 持久化              |

也感谢其他开源 Agent/Bot 项目对这个领域的探索。特别感谢 [MaiBot](https://github.com/MaiM-with-u/MaiBot)，其"数字生命"理念为 AuroraBot 的早期思考提供了重要启发。

## 许可证

本项目以 [Apache License 2.0](LICENSE) 协议开源。
