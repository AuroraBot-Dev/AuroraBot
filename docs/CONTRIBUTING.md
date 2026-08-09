# 参与 AuroraBot

[English](CONTRIBUTING.en.md) | [日本語](CONTRIBUTING.ja.md)

AuroraBot 希望探索的不只是“如何接入一个模型”，而是一个 Agent 如何持续工作、可靠行动，并让人理解她为什么这样做。
无论你带来一个缺陷修复、一段更自然的介绍、一个 MCP 应用，还是一项运行时改进，都欢迎参与。

## 找到适合你的入口

- **第一次贡献**：修正文档、补充测试，或选择边界清晰的小问题。
- **应用开发者**：从内建 Clock 应用出发，为 AuroraBot 接入新的 MCP 能力。
- **运行时开发者**：改进 Agent、Kernel、模型网关、Platform 或本地交互体验。
- **设计参与者**：对公共契约和模块边界提出 RFC，并通过可执行验收标准推动讨论。

如果还不确定从哪里开始，可以先在 Discussion 或 Issue 中描述你希望改善的使用体验。

## 准备开发环境

需要 Python 3.12（推荐，以上版本未经充分验证）、Git 和 [uv](https://docs.astral.sh/uv/)。

```powershell
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
Set-Location AuroraBot
uv sync --group dev
Copy-Item .env.example .env

# 需要实际运行模型时，在 .env 中填写密钥并显式加载
uv run --env-file .env aurora
```

仅运行测试和静态检查不需要真实模型密钥。密钥只写入本地 `.env` 或进程环境；不要提交密钥、真实对话、模型
continuation、工作区事件、上传文件或运行日志。

## 在改动之前

AuroraBot 用 RFC 记录会长期影响项目的设计决策。以下改动应先更新或新增 `docs/rfc/` 中的 RFC：

- 模块职责或依赖方向；
- AMP、Task、Agent、Activity 或效果事件契约；
- TOML 配置、扩展协议或模型调用契约；
- 会改变平台组合、进程入口或持久化语义的行为。

小型缺陷修复、测试补充、文案改进和不改变公共语义的重构可以直接提交。公开说明发生变化时，请同步更新中文、
英文和日文入口。

当前运行时、包边界和进程组合以唯一设计基准 [RFC 0300](rfc/0300-unified-architecture-and-contracts.md) 为准。

## 保持闭环完整

贡献代码时，请守住几条能让 AuroraBot 可靠工作的边界：

- Agent handler 读取 `AgentContext` 并返回 `AgentDecision`，不直接调用 Provider 或平台 Client。
- 外部效果由 Platform 执行，并把 outcome 作为新事件送回运行时；模型普通文本不是效果。
- engine 管理完整热路径，具体模型、工具与记忆实现通过 contracts Port 注入。
- 结构配置继续使用 TOML，密钥继续只来自环境变量。
- 共享日志通过 `src.utils.logging.get_logger()` 获取，不记录完整提示词、continuation 或敏感载荷。

更完整的维护者边界见仓库根目录 `AGENTS.md`。

## 提交你的改进

1. 从 `dev` 创建短生命周期分支，推荐 `feat/`、`fix/` 或 `refact/` 前缀。
2. 让每个 Pull Request 聚焦一个可审查目标，并补充对应测试和文档。
3. 合并目标设为 `dev`，说明使用体验或行为变化、验证命令、已知边界和相关 RFC/Issue。
4. 等待 CI 与评审通过后合并，并删除已经完成的分支。

## 验证

提交前运行统一检查：

```powershell
uv run aurora check
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
- 新行为没有绕过 Agent、Kernel 和 Platform 之间的闭环。
- 配置、README、模块文档、测试和 RFC 没有互相矛盾。
- 日志和测试夹具不包含真实密钥、会话或私人数据。
- `uv run aurora check` 已通过，或 Pull Request 清楚解释了未运行的部分。

提交贡献即表示你同意遵守项目的[社区行为准则](../CODE_OF_CONDUCT.md)。
