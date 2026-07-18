# 参与 AuroraBot

[English](CONTRIBUTING.en.md) | [日本語](CONTRIBUTING.ja.md)

感谢你参与 AuroraBot。项目使用 RFC 固化架构决策，并要求代码、配置、测试和对外描述保持一致。

## 开始之前

需要 Python 3.12、Git 和 [uv](https://docs.astral.sh/uv/)。

```powershell
git clone https://github.com/AuroraBot-Tech/AuroraBot.git
Set-Location AuroraBot
uv sync --group dev
Copy-Item .env.example .env
```

密钥只写入本地 `.env` 或进程环境，禁止提交密钥、真实对话、模型 continuation、工作区事件或运行日志。

## 设计流程

- `docs/rfc/` 是架构与公共契约的唯一基准。
- 影响模块边界、AMP/Kernel 事件、配置、扩展协议或模型调用契约的改动，先更新或新增 RFC。
- 小型缺陷修复、测试补充和不改变语义的重构，可以直接提交代码与验证结果。
- 文档涉及公共行为时，同一提交内同步更新中文、英文和日文入口。

## 模块边界

- Kernel 管理事件、Task/Agent 状态、邮箱、Activity 和因果，不决定认知内容，也不执行平台效果。
- Agent handler 只读取 `AgentContext` 并返回无副作用的 `AgentDecision`。
- Platform 归一化 AMP 输入并执行 `effect.requested`，结果必须作为新事件回到 Kernel。
- `localhost` 承担本地业务用例；`dashboard` 只做路由/API 适配。
- `utils` 不得依赖任何上层包；共享日志必须通过 `src.utils.log_utils.get_logger()` 获取。

## 分支与 Pull Request

1. 从 `dev` 创建短生命周期分支，推荐使用 `feat/`、`fix/` 或 `refact/` 前缀。
2. 每个 PR 聚焦一个可审查目标，补充或更新对应测试和文档。
3. PR 合并目标为 `dev`，说明行为变化、验证命令、已知边界以及相关 RFC/Issue。
4. CI 与评审通过后合并，并删除已完成分支。

## 验证

```powershell
# 项目统一检查入口
uv run aurora check

# 按需单独执行
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

测试必须离线可重复。模型、时钟和 MCP 使用 fake；测试不得消耗真实额度或依赖公网服务。缺陷修复应先覆盖失败路径，
事件与效果测试还需验证事务边界、幂等性和因果父子关系。

## 提交前检查

- 没有绕过 Kernel/Platform 边界，也没有将 Provider 私有对象写入工作区。
- 日志包含定位所需的稳定标识，但不包含密钥、完整提示词、continuation 或敏感载荷。
- 配置仍以 TOML 为结构来源，密钥仍只由环境变量提供。
- README、模块文档、配置样例和 RFC 没有互相矛盾。
- 新行为有测试，且 `uv run aurora check` 通过。

提交贡献即表示你同意遵守项目的[社区行为准则](../CODE_OF_CONDUCT.md)。
