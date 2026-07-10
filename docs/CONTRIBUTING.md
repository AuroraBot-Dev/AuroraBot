# 贡献指南

<b>中文</b> | <a href="./CONTRIBUTING.en.md">English</a> | <a href="./CONTRIBUTING.ja.md">日本語</a>

AuroraBot 正处于 vNext 重建阶段。当前首要工作是建立契约和最小因果闭环，不是恢复 `legacy/` 的全部功能。

## 开始前

- 使用 Python 3.12 与 `uv`。
- 阅读 `docs/rfc/README.md`，以及与改动相关的已接受 RFC。
- `legacy/` 是历史参考，不是可直接迁移的架构模板。

## 贡献规则

1. 改变架构、事件、配置、扩展或模型网关契约时，先修改或新增 RFC。
2. 为每个已接受的契约增加可自动验证的测试；不要只写描述性文档。
3. 不得绕过 Kernel 事件记录直接读写工作区，也不得让 Dashboard 直接调用 Kernel 或 Platform。
4. 不得在 TOML 中写入密钥，不得让 JSON 成为结构性配置。
5. 在 vNext 入口完成前，不要声称 `bot.py` 可启动新系统。

## 开发检查

```bash
uv sync --group dev
uv run ruff check bot.py src/ tests/
uv run ruff format --check bot.py src/ tests/
uv run pyright bot.py src/
uv run pytest --cov=src
```

命令会随着 vNext 入口和测试矩阵的落地更新；提交时以 CI 与已接受 RFC 为准。
