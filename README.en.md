# AuroraBot

<p align="center">
  <a href="README.md">中文</a> | <b>English</b> | <a href="README.ja.md">日本語</a>
</p>

AuroraBot is an autonomous-agent framework built around causal events, graph-based cognition, and an active rhythm.
Environment input, model calls, capability execution, and receipts are recorded so a cognitive episode can pause
asynchronously, resume reliably, and terminate explicitly.

## Cognitive loop

```text
External AMP event / system.tick
  → Kernel creates a bounded Episode and read-only cognitive snapshot
  → builtin.fast_gate handles, invokes, stays silent, or escalates
  → builtin.native_agent runs complex tasks and a bounded tool loop
  → effect.requested
  → Platform executes the capability
  → effect receipt resumes or ends the Episode in a later cycle
```

Model text is not an external effect. Only declared Platform capabilities can produce effects, while every model call,
tool call, receipt, budget change, and termination reason remains in one causal chain. Each external input or autonomous
tick creates an independent Episode. The current loop stores no history across Episodes and does not enable long-term
memory or sandbox nodes.

When no external input arrives, the persistent scheduler emits budgeted `system.tick` events. Repeated silent Episodes
back off from 30 seconds to 30 minutes. External input wakes the runtime immediately, and interactive Episodes take
priority over autonomous work.

## Highlights

- AMP JSON events, Kernel records, and atomic workspace operations
- Bounded Episodes, dynamic continuation edges, budgets, and cancellation policies
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

Use `/say hello` in the console to submit a message, `/cycle` to force one debug cycle, and `/record <record_id>` or
`/status` to inspect audit and scheduler state.

## Layout

```text
config/         TOML configuration and profile overrides
docs/rfc/       Normative architecture and public contracts
src/kernel/     Events, workspace, graph, cycles, causality, and Episodes
src/ai/         Model roles, routing, native tools/Responses, and usage records
src/localhost/  Local chat, scheduler, console, and application use cases
src/dashboard/  Dashboard HTTP/WebSocket and debug route adapters
src/platform/   Ecosystem adapters, capability catalog, and AMP normalization
src/apps/       Built-in native AMP-MCP applications
src/nodes/      Built-in self-contained cognitive nodes
src/sandbox/    Independent sandbox components; not enabled by the current graph
src/utils/      Shared utilities with no upper-layer dependencies
tests/          Contract, integration, and regression tests
```

The Kernel workspace is fixed at `data/kernel/{inbox,process,archive}`. Runtime data is JSON, structural configuration
is TOML, and secrets are supplied only through environment variables.

## Documentation

- [RFC index](docs/rfc/README.md)
- [RFC 0001: Architecture baseline](docs/rfc/0001-architecture.md)
- [RFC 0008: First cognitive graph, Episodes, and active rhythm](docs/rfc/0008-first-cognitive-loop.md)
- [RFC 0010: Dashboard chat adapter](docs/rfc/0010-dashboard-chat.md)
- [RFC 0011: Current project baseline](docs/rfc/0011-current-project-baseline.md)
- [Contributing guide](docs/CONTRIBUTING.en.md)
- [Logging policy](LOGGING.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)

## License

Licensed under the [Apache License 2.0](LICENSE).
