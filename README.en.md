# AuroraBot

AuroraBot is an autonomous-agent framework built around a tree of homogeneous Agents that understand messages, use tools,
delegate work, and resume their parents.

One run is one `AgentTree`. Root and child nodes share the same loop and differ only in system profile, initial message,
visible tools, and LLM model. The core uses four domain roles: `system`, `message`, `assistant`, and `tool`.

`config.example/` ships with the source. Users copy it to the Git-ignored `config/` directory; the runtime never falls back to the template.
Project TOML files and Markdown prompts are merged into one `AuroraConfig`, and `aurora config list/show` provides read-only access.

```bash
uv sync
cp -r config.example config
uv run aurora check
uv run aurora about
```

Concrete Models and Tools are injected by the caller. See [architecture docs](docs/architecture/index.md) and the
[authoritative RFC](docs/rfc/0300-unified-architecture-and-contracts.md).
