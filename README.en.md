# AuroraBot

<p align="center">
  <a href="README.md">中文</a> | <b>English</b> | <a href="README.ja.md">日本語</a>
</p>

AuroraBot is an autonomous-agent framework built around causal events, homogeneous Agents, and an active rhythm.
Environment input, model calls, capability execution, and receipts are recorded so a Task can pause
asynchronously, resume reliably, and terminate explicitly.

## Cognitive loop

```text
External AMP event / system.tick
  → Kernel creates a Task and root Gate Agent
  → an Agent requests a model Activity or delegates bounded parallel child Agents
  → each child reports completion to its parent, which resumes immediately
  → authorized Agents request ordinary effects; only the root may publish terminal effects
  → Platform receipts return as mailbox messages to the requesting Agent
```

Model text is not an external effect. Only declared Platform capabilities can produce effects, while every model call,
tool call, receipt, budget change, and termination reason remains in one causal chain. Each external input or autonomous
tick creates an independent Task. The supervision tree shares model, tool, and time budgets. Runtime projects a global,
read-only Brain Context for every Agent. Long-term memory currently exposes only an optional Memory Agent contract.

When no external input arrives, the persistent scheduler emits budgeted `system.tick` events. Repeated silent Tasks
back off from 30 seconds to 30 minutes. External input wakes the runtime immediately, and interactive Tasks take
priority over autonomous work.

## Highlights

- AMP JSON boundaries, SQLite WAL runtime state, and atomic archives
- Durable mailboxes, homogeneous Agents, supervision trees, shared budgets, and cancellation propagation
- A model gateway supporting both Chat Completions tools and a Responses agent
- Immutable capability catalogs, JSON Schema argument validation, and MCP applications
- One-process `AuroraRuntime` for the scheduler, Kernel, model dispatcher, and Platform receipts
- Context-rich structured logs backed by separate causal audit records

## Quick start

Python 3.12 and [uv](https://docs.astral.sh/uv/) are required.

```powershell
uv sync --group dev
Copy-Item .env.example .env
# Add the API keys required by your configured providers to .env
uv run python bot.py
```

This starts both the cognitive loop and the Dashboard backend at `http://127.0.0.1:8000`. Run the separate UI with:

```powershell
Set-Location ..\AuroraChat
pnpm install
pnpm run dev
```

Open `http://localhost:5173`, register, and chat with another user or the built-in AuroraBot contact.

Common entry points:

```powershell
# Cognitive loop only, without Dashboard
uv run python bot.py --headless --profile prod

# Debug API and local console together
uv run aurora

# Debug API or console separately
uv run aurora serve
uv run aurora console

# Project quality checks
uv run aurora check
```

Use `/say hello` in the console to submit a message, `/pump` to advance ready turns, and `/task <task_id>`,
`/agent <agent_id>`, or `/status` to inspect the supervision tree and scheduler.

## Layout

```text
config/         TOML configuration and profile overrides
docs/rfc/       Normative architecture and public contracts
src/kernel/     Tasks, Agents, mailboxes, Activities, causality, and SQLite runtime state
src/agents/     Homogeneous Agent handlers and built-in delegation capabilities
src/ai/         Model roles, routing, native tools/Responses, and usage records
src/localhost/  Local chat, scheduler, console, and application use cases
src/dashboard/  Dashboard HTTP/WebSocket and debug route adapters
src/platform/   Ecosystem adapters, capability catalog, and AMP normalization
src/apps/       Built-in native AMP-MCP applications
src/sandbox/    Independent sandbox components; not enabled by the current Agent runtime
src/utils/      Shared utilities with no upper-layer dependencies
tests/          Contract, integration, and regression tests
```

The Kernel workspace is fixed at `data/kernel/{inbox,process,archive}`. External boundaries and archives use JSON,
runtime state uses SQLite WAL, structural configuration uses TOML, and secrets come only from environment variables.

## Documentation

- [RFC index](docs/rfc/README.md)
- [RFC 0001: Architecture baseline](docs/rfc/0001-architecture.md)
- [RFC 0012: Homogeneous multi-Agent durable runtime](docs/rfc/0012-homogeneous-agent-runtime.md)
- [RFC 0010: Dashboard chat adapter](docs/rfc/0010-dashboard-chat.md)
- [RFC 0011: Current project baseline](docs/rfc/0011-current-project-baseline.md)
- [Contributing guide](docs/CONTRIBUTING.en.md)
- [Logging policy](LOGGING.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)

## License

Licensed under the [Apache License 2.0](LICENSE).
