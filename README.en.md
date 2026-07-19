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
uv run aurora
```

The default Platform set comes from `config/preference.toml`. The repository defaults enable Console, Dashboard, and
MCP. Run the separate Dashboard UI with:

```powershell
Set-Location ..\AuroraChat
pnpm install
pnpm run dev
```

Open `http://localhost:5173`, register, and chat with another user or the built-in AuroraBot contact.

Common entry points:

```powershell
# Cognitive loop only, without an external Platform
uv run aurora --profile prod --headless

# Use the default Platform set from preference.toml
uv run aurora

# Explicit flags form the exact Platform set; they do not extend the defaults
uv run aurora --dashboard --mcp
uv run aurora --console

# Project quality checks
uv run aurora check
```

Console and Dashboard share slash commands. Use `/say hello`, `/pump`, `/task <task_id>`, `/agent <agent_id>`, or
`/status`; `/log off` silences terminal logs while file logging continues.

## Layout

```text
config/         Core TOML, Platform preferences, domain configuration, and profile overrides
aurora/         Process CLI, Platform composition, and unified lifecycle
docs/rfc/       Normative architecture and public contracts
src/contracts/  Configuration, AMP, Agent, model, and memory contracts
src/kernel/     Tasks, Agents, mailboxes, Activities, causality, and SQLite runtime state
src/agents/     Homogeneous Agent handlers and built-in delegation capabilities
src/ai/         Model roles, routing, native tools/Responses, and usage records
src/localhost/  Unified ingress, effect dispatch, scheduler, and developer use cases
src/platform/   Console, Dashboard, and MCP protocols, persistence, and effect adapters
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
- [RFC 0013: Unified command routing and Aurora process entry](docs/rfc/0013-unified-command-routing-and-entry.md)
- [RFC 0014: Parallel Platform composition and preferences](docs/rfc/0014-parallel-platform-composition-and-preferences.md)
- [RFC 0010: Dashboard chat adapter](docs/rfc/0010-dashboard-chat.md)
- [RFC 0011: Current project baseline](docs/rfc/0011-current-project-baseline.md)
- [Contributing guide](docs/CONTRIBUTING.en.md)
- [Logging policy](LOGGING.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)

## License

Licensed under the [Apache License 2.0](LICENSE).
