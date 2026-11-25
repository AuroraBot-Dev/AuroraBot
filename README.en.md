# AuroraBot

[简体中文](README.md) · [日本語](README.ja.md)

AuroraBot is an agent framework for continuously running bots, with ReAct execution, model and MCP tool integration, persistent state, environment observation, and terminal and web interfaces.

The execution dependency direction is `bot → agent → control → core`. `aurora_config` manages configuration, while `aurora_adapter` handles model and MCP protocols. CLI, HTTP / WebSocket API, TUI and Panel share backend execution semantics.

## Getting started

Install Python 3.12+, [uv](https://docs.astral.sh/uv/) and Git:

```bash
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot
uv sync --locked --all-packages
uv run --locked python examples/onboarding/main.py --init
```

Follow the [first-run guide](examples/START.md) to configure the model and environment variables, then start the onboarding assistant. It uses a separate data directory. Conversations call your configured model provider; initialization and ordinary tests do not call real models.

TUI, Panel and frontend development require the Node.js and pnpm versions declared in [package.json](package.json) and [.node-version](.node-version).

## Documentation and development

- [Documentation index](docs/INDEX.md): configuration, operations, context and architecture.
- [Operations](docs/operations.md): starting and connecting Bot, TUI, Panel and API.
- [Development and validation](docs/development.md).
- [Contributing](.github/CONTRIBUTING.en.md) and [code of conduct](.github/CODE_OF_CONDUCT.md).
- [Changes and validation results](docs/CHAGELOG.md).

The linked technical documentation is maintained in Simplified Chinese.

```bash
pnpm install --frozen-lockfile
pnpm exec uv run --locked aurora check
pnpm exec uv run --locked aurora check --full
```

## Community

Report bugs and request features in [Issues](https://github.com/AuroraBot-Dev/AuroraBot/issues), join [Discussions](https://github.com/AuroraBot-Dev/AuroraBot/discussions), or [support the project](https://ifdian.net/a/aurorabot). Remove credentials, real conversations and private data before sharing logs.

Licensed under the [Apache License 2.0](LICENSE).
