# Contributing

<a href="./CONTRIBUTING.md">中文</a> | <b>English</b> | <a href="./CONTRIBUTING.ja.md">日本語</a>

AuroraBot is in its vNext rebuild phase. The immediate goal is a contractual minimum causal loop, not restoration of every feature in `legacy/`.

## Before contributing

- Use Python 3.12 and `uv`.
- Read `docs/rfc/README.md` and every accepted RFC affected by the change.
- Treat `legacy/` as historical reference, not as an architectural template.

## Rules

1. Update or add an RFC before changing architecture, events, configuration, extensions, or the model-gateway contract.
2. Add executable tests for every accepted contract.
3. Do not bypass Kernel event recording to manipulate the workspace; Dashboard must not call Kernel or Platform directly.
4. Never place secrets in TOML or use JSON as structural configuration.
5. Until the vNext entry point exists, do not describe `bot.py` as the vNext launch command.

## Checks

```bash
uv sync --group dev
uv run aurora check
```

Equivalent to running `ruff check`, `ruff format --check`, `pyright`, `pytest --cov=src` in sequence.

Commands will evolve with the vNext implementation. CI and accepted RFCs remain authoritative.
