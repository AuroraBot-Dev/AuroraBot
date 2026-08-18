# AuroraBot

AuroraBot is currently an experimental core for one question: how can homogeneous Agents understand messages, use tools,
delegate work, and resume through a tree-shaped runtime?

One run is one `AgentTree`. Root and child nodes share the same loop and differ only in system profile, initial message,
visible tools, and LLM model. The core uses four domain roles: `system`, `message`, `assistant`, and `tool`.

The repository deliberately excludes persistence, recovery, automatic memory, triage, MCP, the Panel backend, sandboxing,
and production extension machinery. It retains the project composition path from `config/aurora.toml` through
`assemble_runtime()` to `AuroraRuntime`.

```bash
uv sync
uv run aurora check
uv run aurora about
```

Concrete Models and Tools are injected by the caller. See [ARCHITECTURE.md](ARCHITECTURE.md) and the
[authoritative RFC](docs/rfc/0300-unified-architecture-and-contracts.md).
