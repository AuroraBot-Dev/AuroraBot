# AuroraBot

AuroraBot is an autonomous-agent framework built around a tree of homogeneous Agents that understand messages, use tools,
delegate work, and resume their parents.

One run is one `AgentTree`. Root and child nodes share the same loop and differ only in system profile, initial message,
visible tools, and LLM model. The core uses four domain roles: `system`, `message`, `assistant`, and `tool`.

Runtime, engine, and prompt TOML files are registered by matching configuration modules and merged into one `AuroraConfig`.
Matching composition modules construct the project instances used by `AuroraRuntime`.

```bash
uv sync
uv run aurora check
uv run aurora about
```

Concrete Models and Tools are injected by the caller. See [ARCHITECTURE.md](ARCHITECTURE.md) and the
[authoritative RFC](docs/rfc/0300-unified-architecture-and-contracts.md).
