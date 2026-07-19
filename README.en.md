<p align="center">
  <img src="assets/logo.svg" width="112" alt="AuroraBot Logo" />
</p>

<h1 align="center">AuroraBot</h1>

<p align="center">
  <a href="README.md">中文</a> | <b>English</b> | <a href="README.ja.md">日本語</a>
</p>

<p align="center">
  <em>An autonomous-agent framework with an active rhythm, durable work, and a traceable reason behind every action.</em>
</p>

<p align="center">Causal events · Homogeneous Agents · Active rhythm</p>

<p align="center">
  <a href="https://github.com/AuroraBot-Dev/AuroraBot"><img src="https://img.shields.io/badge/GitHub-AuroraBot-181717?logo=github" alt="GitHub" /></a>
  <a href="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml"><img src="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-315b7d" alt="Apache 2.0" /></a>
  <img src="https://img.shields.io/badge/Python-3.12-315b7d?logo=python&logoColor=white" alt="Python 3.12" />
</p>

## What is AuroraBot?

AuroraBot is an open-source autonomous-agent framework for developers. Instead of treating an agent as a sequence of
isolated questions and answers, it turns environmental changes, model reasoning, capability calls, and outcomes into a
continuous experience that can pause, resume, and be inspected later.

When nobody is speaking, AuroraBot can still wake on its own rhythm and decide whether the moment calls for action.
When work grows complex, homogeneous Agents can collaborate through bounded delegation. When an Agent needs to affect
the outside world, only declared and authorized capabilities are allowed to do so.

> She is not waiting for instructions. She keeps observing, deciding, and acting.

## What can you build with it?

- **Agents that wake proactively:** a durable scheduler creates budgeted autonomous moments while external messages
  immediately return priority to interactive work.
- **Natural division of complex work:** an Agent handles simple requests directly or delegates bounded subtasks, then
  resumes when their results arrive.
- **Real-world capabilities:** MCP applications can provide time, reminders, or other tools, with authorization and
  argument validation before use.
- **Several ways to meet the Agent:** talk through the local Console, connect a separate Dashboard UI, or embed the
  runtime headlessly in your own environment.
- **An understandable trail of action:** inputs, model calls, tool requests, receipts, and termination reasons share one
  causal record.

The repository includes a Clock MCP application for time, alarms, and timers. It is both a useful capability and a
minimal example for adding your own application.

## A real journey

Suppose you say, “Remind me about the meeting at 7 PM.” AuroraBot does not pretend that model text is a completed action:

1. Your message becomes an environmental event and wakes an independent Task.
2. The root Agent understands the request and selects the authorized Clock capability.
3. Clock returns a structured receipt, so the Task knows the reminder was actually scheduled.
4. At the due time, Clock emits a new environmental event and wakes AuroraBot again.
5. AuroraBot uses the current Platform to deliver the reminder to you.

This loop is what separates AuroraBot from a simple “prompt in, text out” wrapper: the model decides, while the runtime
makes action happen reliably.

## Quick start

You need Python 3.12, Git, and [uv](https://docs.astral.sh/uv/). Running from source is currently the supported path.

```powershell
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
Set-Location AuroraBot
uv sync --no-dev
Copy-Item .env.example .env

# Add the DEEPSEEK_API_KEY required by the default configuration to .env
uv run --no-dev --env-file .env aurora --console --mcp
```

Type a message after startup, use `/help` to discover commands, or `/status` to inspect the current runtime.

### Choose how to run

```powershell
# Use config/preference.toml: Console, Dashboard backend, and MCP by default
uv run --no-dev --env-file .env aurora

# Start only the local Console
uv run --no-dev --env-file .env aurora --console

# Run the Kernel and active rhythm without an external Platform
uv run --no-dev --env-file .env aurora --headless
```

When any of `--console`, `--dashboard`, or `--mcp` is present, those flags form the exact Platform set rather than
extending the defaults. The Dashboard UI is maintained separately; this repository contains its local backend and chat
bridge, not the browser interface.

## Make the Agent yours

AuroraBot keeps common customization points in focused configuration files:

| What you want to change | Start here |
| --- | --- |
| Persona, voice, and conversational boundaries | `config/prompts/SOUL.md` |
| Model roles and Providers | `config/aurora.toml` |
| Platforms enabled by default | `config/preference.toml` |
| Agent models, capabilities, and delegation limits | `config/agents.toml` |
| Local or remote MCP applications | `config/apps.toml` |

Structural configuration uses TOML, and secrets come only from environment variables. Extensions do not need direct
Kernel access. Start with the [extension guide](extensions/README.md) and the built-in
[Clock application](src/apps/aurora-app-clock/README.md).

## Current stage

AuroraBot `0.4` is a developer preview intended for local exploration, runtime research, and extension development. It
does not yet ship built-in long-term memory, attachment understanding, an Agent sandbox tool, or production-grade
multi-tenant guarantees. Dashboard debug endpoints should remain within the local-machine boundary.

We prefer to state unfinished work clearly rather than present a roadmap as current capability. Accepted RFCs and tests
define public behavior today.

## Keep reading

- [Contributing guide](docs/CONTRIBUTING.en.md): set up a development environment and submit improvements
- [Extending AuroraBot](extensions/README.md): connect MCP applications and Agent profiles
- [Model gateway](src/ai/README.md): understand model roles, capabilities, and endpoints
- [RFC reading guide](docs/rfc/README.md): find the currently authoritative design decisions
- [Logging policy](LOGGING.md): diagnostics, privacy, and audit boundaries
- [Code of Conduct](CODE_OF_CONDUCT.md): help maintain a welcoming open-source community

## Open source

AuroraBot is licensed under the [Apache License 2.0](LICENSE). We believe a good agent framework should belong to everyone.
