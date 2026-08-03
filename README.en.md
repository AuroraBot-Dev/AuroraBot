<p align="center">
  <img src="assets/logo.svg" width="112" alt="AuroraBot Logo" />
</p>

<h1 align="center">AuroraBot</h1>

<p align="center">
  <a href="README.md">中文</a> | <b>English</b> | <a href="README.ja.md">日本語</a>
</p>

<p align="center"><em>Give an Agent a life of its own.</em></p>

<p align="center">Event equality · Homogeneous collaboration · Active rhythm</p>

<p align="center">
  <a href="https://github.com/AuroraBot-Dev/AuroraBot"><img src="https://img.shields.io/badge/GitHub-AuroraBot-181717?logo=github" alt="GitHub" /></a>
  <a href="https://www.aurorabot.org/"><img src="https://img.shields.io/badge/Docs-aurorabot.org-315b7d" alt="Documentation" /></a>
  <a href="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml"><img src="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-315b7d" alt="Apache 2.0" /></a>
  <img src="https://img.shields.io/badge/Python-3.12-315b7d?logo=python&logoColor=white" alt="Python 3.12" />
</p>

## What is AuroraBot?

AuroraBot is an open-source autonomous-agent framework for developers. Our goal is not simply a chatbot with more features, but an Agent that persists, develops its own rhythm, and can judge and act within an environment.

We refer to the Agent as “she.” This is more than a writing style: AuroraBot is not designed as an on-demand tool that exists only when called. It provides a runtime in which a digital life can have a persona, state, boundaries, and its own work while still forming meaningful connections with people and the outside world.

## Design philosophy

### An Agent with a life of its own

Conversation is not the whole world. Time continues, applications emit events, and unfinished work can progress even when nobody sends a message. An active rhythm lets the Agent decide, within explicit budgets and boundaries, whether a moment calls for thought or action.

### Treat environmental changes equally

User messages, the passage of time, application events, child-Agent results, and effect receipts are all changes in the outside world. They enter cognition through the same event boundary. A message does not become an unquestionable highest-priority command merely because it came from a user.

Equality does not mean the absence of scheduling priorities. Interactive work can run first, and authorization and safety rules still apply. It means the Agent understands what happened before deciding whether to respond, act, delegate, or remain quiet.

### Separate judgment from action

Models interpret and decide, but ordinary model text cannot directly change the environment. External actions pass through declared capabilities, argument validation, and Platform execution. Outcomes then return to the Agent as new events. Autonomy does not have to mean loss of control.

## Highlights

- **Active runtime:** the built-in Clock MCP persists a heartbeat that creates budgeted autonomous Tasks and yields promptly to external interaction.
- **Continuing Tasks:** work can await models, capabilities, and child Agents, then resume with explicit budgets and terminal states.
- **Multi-Agent collaboration:** homogeneous Agents form bounded supervision trees and can split complex work concurrently.
- **Connections to the world:** Console, Dashboard, and MCP Platforms normalize inputs and expose authorized capabilities.
- **Replaceable models:** model roles, Providers, Chat Completions, and Responses are selected through configuration.
- **Traceable action:** inputs, model calls, capability requests, outcomes, and termination reasons share one causal record.
- **Configurable identity and ability:** SOUL, Agent profiles, model roles, Platforms, and MCP applications have focused entry points.

## Quick start

You need Python 3.12, Git, and [uv](https://docs.astral.sh/uv/). Running from source is currently recommended.

```powershell
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
Set-Location AuroraBot
uv sync --no-dev
Copy-Item .env.example .env

# Add the DEEPSEEK_API_KEY required by the default configuration to .env
uv run --no-dev --env-file .env aurora --console --mcp
```

Type a message after startup, use `/help` to discover commands, or `/status` to inspect the runtime.

```powershell
# Use the default Platform set from config/platforms.toml
uv run --no-dev --env-file .env aurora

# Start only the local Console
uv run --no-dev --env-file .env aurora --console

# Run without an external Platform
uv run --no-dev --env-file .env aurora --headless
```

When any of `--console`, `--dashboard`, or `--mcp` is present, those flags form the exact Platform set rather than extending the defaults. The Dashboard browser UI is maintained separately; this repository contains its local backend and chat bridge.

## Customize and extend

| What you want to change                           | Start here               |
| ------------------------------------------------- | ------------------------ |
| SOUL, world, and Agent prompt fragments            | `config/prompts.toml`    |
| Model roles and Providers                         | `config/models.toml`     |
| Engine limits and Task budgets                    | `config/engine.toml`     |
| Persistent storage paths                          | `config/storage.toml`    |
| Platforms enabled by default                      | `config/platforms.toml` |
| Agent models, capabilities, and delegation limits | `config/agents.toml`     |
| Local or remote MCP applications                  | `config/apps.toml`       |

Structural configuration uses TOML, and secrets come only from environment variables. Start with the [extension guide](extensions/README.md) and the built-in [Clock application](src/apps/aurora-app-clock/README.md).

## Current stage

AuroraBot `0.4` is a developer preview for local exploration, runtime research, and extension development. It does not yet ship built-in long-term memory, attachment understanding, an Agent sandbox tool, or production-grade multi-tenant guarantees. Current capability and roadmap remain clearly separated; accepted RFCs and tests define public behavior.

## Documentation

- [AuroraBot documentation](https://www.aurorabot.org/)
- [Contributing guide](docs/CONTRIBUTING.en.md)
- [Extending AuroraBot](extensions/README.md)
- [Model gateway](src/ai/README.md)
- [RFC reading guide](docs/rfc/README.md)
- [Logging policy](LOGGING.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)

## Open-source acknowledgements

AuroraBot uses many excellent open-source projects:

| Project                                                                                                                | Use in AuroraBot                                   |
| ---------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| [LiteLLM](https://github.com/BerriAI/litellm)                                                                          | Model Provider integration and call infrastructure |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)                                                   | MCP applications and tool protocol                 |
| [FastAPI](https://github.com/fastapi/fastapi) / [Uvicorn](https://github.com/encode/uvicorn)                           | Local Dashboard service                            |
| [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) / [Rich](https://github.com/Textualize/rich) | Console and terminal experience                    |
| [jsonschema](https://github.com/python-jsonschema/jsonschema)                                                          | Capability argument validation                     |

Thanks also to the other open-source Agent and Bot projects exploring this field. Special thanks to [MaiBot](https://github.com/MaiM-with-u/MaiBot), whose idea of "digital life" was an important influence on AuroraBot's early thinking.

## License

This project is open source under the [Apache License 2.0](LICENSE).
