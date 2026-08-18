# AuroraBot

AuroraBot は、同型 Agent が message を理解し、tool を使い、仕事を委任して、木構造の runtime で親を再開する
自律 Agent フレームワークです。

一回の実行は一つの `AgentTree` です。root と child は同じ loop を使い、system profile、最初の message、可視 tools、
LLM model だけが異なります。domain role は `system / message / assistant / tool` の四種類です。

runtime、engine、prompt の TOML は同名 configuration module から登録され、一つの `AuroraConfig` に統合されます。
同名 composition module が `AuroraRuntime` で使う project instance を構築します。

```bash
uv sync
uv run aurora check
uv run aurora about
```

詳細は [ARCHITECTURE.md](ARCHITECTURE.md) と [RFC](docs/rfc/0300-unified-architecture-and-contracts.md) を参照してください。
