# AuroraBot

AuroraBot は現在、同型 Agent が message を理解し、tool を使い、仕事を委任して、木構造の runtime で再開するための
最小コアを検証する実験的フレームワークです。

一回の実行は一つの `AgentTree` です。root と child は同じ loop を使い、system profile、最初の message、可視 tools、
LLM model だけが異なります。domain role は `system / message / assistant / tool` の四種類です。

現在は永続化、復旧、自動 memory、triage、MCP、Panel backend、sandbox、production extension 機構を含みません。一方、
`config/aurora.toml → assemble_runtime() → AuroraRuntime` という project composition は維持しています。

```bash
uv sync
uv run aurora check
uv run aurora about
```

詳細は [ARCHITECTURE.md](ARCHITECTURE.md) と [RFC](docs/rfc/0300-unified-architecture-and-contracts.md) を参照してください。
