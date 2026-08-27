# 参与 AuroraBot

<b>中文</b> | <a href="CONTRIBUTING.en.md">English</a> | <a href="CONTRIBUTING.ja.md">日本語</a>

AuroraBot 想做的不是一个工具一般的 Agent，而是一个能够持续存在、形成自己的节律、在自己世界里自主判断和行动的 Bot。
我们探索的不只是"如何接入一个模型"，而是她如何持续工作、可靠行动，并让人理解她为什么这样做。
无论你带来一个缺陷修复、一段更自然的介绍、一个 MCP 应用，还是一项运行时改进，都欢迎参与。

## 找到适合你的入口

- **第一次贡献**：修正文档、补充测试，或选择边界清晰的小问题。
- **应用开发者**：从内建 Clock 应用出发，为 AuroraBot 接入新的 MCP 能力。
- **运行时开发者**：改进 AgentTree、engine、模型网关、MCP 适配或本地交互体验。
- **设计参与者**：对公共契约和模块边界提出 RFC，并通过可执行验收标准推动讨论。

如果还不确定从哪里开始，可以先在 Discussion 或 Issue 中描述你希望改善的使用体验。

## 准备开发环境

### 1. 克隆本仓库

需要 Python 3.12（推荐，以上版本未经充分验证）、Git 和 [uv](https://docs.astral.sh/uv/)。
文档或面板开发还需要 [Node.js](https://nodejs.org/) 与 [pnpm](https://pnpm.io/)。

```bash
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot
./scripts/linux/setup.sh
# macOS: ./scripts/macos/setup.command;
# Windows: .\scripts\windows\setup.ps1.
```

`setup.sh` 会把 aurora 安装到用户工具目录，并完成依赖同步、个人配置以及 docs/panel 子模块引导。

### 2. 填写必要配置

在 `.env` 中填入默认模型所需密钥（如 `DEEPSEEK_API_KEY`）

### 3. 从终端启动

```bash
aurora start
```

启动后直接输入消息即可对话；输入 `/help` 查看操作，输入 `/exit` 停止。

仅运行测试和静态检查不需要真实模型密钥。密钥只写入本地 `.env` 或进程环境；不要提交密钥、真实对话、完整模型回复、工作区事件、上传文件或运行日志。

## 在改动之前

AuroraBot 用 RFC 记录会长期影响项目的设计决策。以下改动应先更新或新增 `docs/rfc/` 中的 RFC：

- 模块职责或依赖方向；
- AgentTree、委派与工具回执契约；
- TOML 配置、扩展协议或模型调用契约；
- 会改变平台组合、进程入口或持久化语义的行为。

小型缺陷修复、测试补充、文案改进和不改变公共语义的重构可以直接提交。公开说明发生变化时，请同步更新中文、英文和日文入口。

当前运行时、包边界和进程组合以唯一设计基准 [RFC 0300](docs/rfc/0300-unified-architecture-and-contracts.md) 为准。

## 保持闭环完整

贡献代码时，请守住几条能让 AuroraBot 可靠工作的边界：

- 模型决定、运行时执行：assistant 只能回复或请求工具，真实外部效果只由 Tool 契约执行，普通模型文本不是效果；
- 委派就是树操作：`aur.agent.delegate` 是普通可见 Tool，由 engine 解释并创建 child，child 完成后以 tool
  结果恢复 parent；
- engine 管理完整热路径，具体模型、工具与记忆实现通过 contracts Port 注入，节点不直接调用模型网关或平台客户端；
- 结构配置继续使用 TOML，密钥继续只来自环境变量；
- 共享日志通过 `src.utils.logging.get_logger()` 获取，不记录完整提示词、模型回复或敏感载荷。

更完整的维护者边界见仓库根目录 `AGENTS.md`。

## AIGC

AuroraBot 欢迎使用 AI 辅助开发，但生成的内容同样受项目边界约束，不能因为是"AI 写的"而获得豁免：

- **必须可验证**：AI 生成或大幅修改的代码必须通过 `aurora check` 全部检查，并配套离线、确定、可重复的测试；
- **必须理解并负责**：提交者必须逐行理解生成代码，能解释其行为，并对其正确性与安全性负责；
- **必须守边界**：生成代码保持既有依赖方向与契约，不引入平行运行模型或绕过闭环的旁路；
- **不得掩盖质量**：不用 lint ignore 掩盖生成代码的复杂度；单文件原则上不允许超过 600 行；
- **不得替换底座**：panel 等子模块的 `packages/@core` 等底座代码不接受 AI 整段替换；
- **文本以中文为准**：生成的面向用户文案以简体中文为权威版本，不写"实验、重构、旧版、迁移"等历史阶段叙事，不虚构能力、API 或示例数据；
- **来源与安全**：不引入来源不明或许可证不兼容的代码，不生成并提交密钥、真实会话或私人数据；
- **如实披露**：在 Pull Request 描述中说明哪些内容由 AI 生成或辅助，便于评审聚焦。

违反后果：

- 评审发现违反以上约束的 PR 会被打回，要求修改或重写相关部分；
- 未运行 `aurora check` 且未说明原因的 PR 不予合入；
- 重复或严重违反（如泄漏密钥、伪造测试结果、绕过安全或架构边界）的 PR 将被关闭，维护者会保留记录，并可能限制后续贡献。

## 提交你的改进

1. 从 `dev` 创建短生命周期分支，推荐 `feat/`、`fix/` 或 `refact/` 前缀。
2. 让每个 Pull Request 聚焦一个可审查目标，并补充对应测试和文档。
3. 合并目标设为 `dev`，说明使用体验或行为变化、验证命令、已知边界和相关 RFC/Issue。
4. 等待 CI 与评审通过后合并，并删除已经完成的分支。

## 验证

提交前运行统一检查：

```powershell
aurora check
```

需要缩小范围时，可以分别运行：

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

测试必须离线、确定且可重复。模型、时钟和 MCP 使用 fake，不消耗真实额度或依赖公网服务。缺陷修复应覆盖原始失败路径；
事件与效果测试还应验证事务边界、幂等性和因果父子关系。

## 提交前自查

- 使用者能从文档或测试看懂改动带来的行为差异。
- 新行为没有绕过模型决定、Tool 执行与世界提交的闭环。
- 配置、README、模块文档、测试和 RFC 没有互相矛盾。
- 日志和测试夹具不包含真实密钥、会话或私人数据。
- `aurora check` 已通过，或 Pull Request 清楚解释了未运行的部分。

提交贡献即表示你同意遵守项目的[社区行为准则](CODE_OF_CONDUCT.md)。
