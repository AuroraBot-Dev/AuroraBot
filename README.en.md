<p align="center">
  <img src="assets/logo.svg" width="112" alt="AuroraBot Logo" />
</p>

<h1 align="center">AuroraBot</h1>

<p align="center">
  <a href="README.md">中文</a> | <b>English</b> | <a href="README.ja.md">日本語</a>
</p>

<p align="center">
  <em>Give an Agent a life of its own.</em>
</p>

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

One run is one `AgentTree`: root and child nodes share the same deterministic loop, are created from predefined `AgentDefinition`s, and differ only in prompt, initial message, visible tools, and LLM model.

We refer to the Agent as "she." This is more than a writing style: AuroraBot is not designed as an on-demand tool that exists only when called. It provides a runtime in which a digital life can have a persona, state, and boundaries of her own, and can still connect with people and the outside world when needed.

## Design philosophy

### An Agent with a life of its own

Conversation is not the whole world. Time continues, applications emit events, and unfinished work can progress even when nobody sends a message. An active rhythm (cadence) lets the Agent decide, within explicit budgets and boundaries, whether a moment calls for thought or action, instead of waiting forever behind an input box.

### Treat environmental changes equally

User messages, the passage of time, application events, child-Agent results, and effect receipts are all changes in the outside world. They enter cognition through the same event boundary (the worldline). A message does not become an unquestionable highest-priority command merely because it came from a user.

Equality does not mean the absence of priorities. Interactive work can be scheduled first, and authorization and safety rules still apply. It means the Agent understands what happened before deciding whether to respond, act, delegate, or remain quiet.

### Separate judgment from action

Models interpret and decide, but ordinary model text cannot directly change the environment. External actions pass through declared capabilities, argument validation, and execution; outcomes then return to the Agent as new events. Autonomy does not have to mean loss of control.

## Highlights

```text
message → model → assistant
                  ├── Tool call → tool result → model
                  └── aur.agent.delegate → child Agent → tool result → parent
```

- **Active runtime:** cadence makes time itself an input — even without messages, the Agent is evoked on its own rhythm and decides whether to act;
- **Homogeneous collaboration:** root and child share one loop; `aur.agent.delegate` delegates to child Agents as a real Tool, splitting complex work into an AgentTree;
- **Event equality:** user messages, the passage of time, and application events enter cognition through one worldline; continuous event streams and observation frontiers across scopes keep the Agent in sync with the outside world;
- **Connections to the world:** the local Console, the Panel backend, and the MCP SDK 2.x client (stdio / HTTPS Streamable HTTP) normalize different sources into events;
- **Built-in memory:** recent commits from active scopes are injected into system via the PromptAssembler, with deterministic truncation for over-long contexts;
- **Replaceable models:** a unified LiteLLM gateway maps roles and Providers through TOML; secrets are read only from environment variables;
- **Traceable action:** inputs, model calls, tool requests, and outcomes share one causal record (WorldJournal);
- **Configurable identity and ability:** SOUL, WORLD, Agent prompts, model roles, and tool visibility each have focused configuration entry points;
- **Unified operation catalog:** runtime capabilities (engine, world, ai, console, cadence, memory, MCP) expose consistent method/path and slash-text entries (ops);
- **Fully offline tests:** fake Models and Tools keep the test suite deterministic, offline, and network-free.

The scope excludes Panel attachments and WebSocket, sandbox, a general extension platform, and MCP sampling, elicitation, roots, Tasks, or non-text result injection.

## Quick start

You need Python 3.12, Git, and [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot
uv sync
cp -r config.example config
cp .env.example .env
uv run aurora start
```

`aurora start` reads `.env` from the project root (fill in the key the default model needs, e.g. `DEEPSEEK_API_KEY`) and builds the model gateway from `models.toml`. Type a message after startup to chat; use `/help` to discover operations and `/exit` to stop. Add `--headless` to run without the local Console:

```bash
uv run aurora start --headless
```

## Customize and extend

| What you want to change                           | Start here                              |
| ------------------------------------------------- | --------------------------------------- |
| SOUL, world, and Agent prompts                    | `config/prompts.toml`, `config/prompts/` |
| Model roles and Providers                         | `config/models.toml`                    |
| Agent definitions and delegation scope            | `config/agents.toml`                    |
| Engine limits and tree structure                  | `config/engine.toml`, `config/runtime.toml` |
| Rhythm and memory                                 | `config/cadence.toml`, `config/memory.toml` |
| Local or remote MCP applications                  | `config/apps.toml`                      |
| Logging and storage paths                         | `config/logging.toml`, `config/storage.toml` |

Structural configuration uses TOML, and secrets come only from environment variables.

## Development

`config.example/` ships with the source; the copied `config/` is personal and Git-ignored. Common commands:

```bash
uv run aurora check        # lint, types, and tests
uv run aurora about        # learn about AuroraBot
uv run aurora config list  # list registered configurations
uv run aurora setup        # full bootstrap: dependencies, submodules, and panel
```

The architecture is defined by [RFC 0300](docs/rfc/0300-unified-architecture-and-contracts.md); see the
[architecture documentation](docs/architecture/index.md) for per-package details.

## Documentation

- [Getting started](docs/start/getting-started.md)
- [Configuration](docs/start/configuration.md)
- [Architecture overview](docs/architecture/index.md)
- [Current implementation status](docs/reference/nightly-status.md)
- [Contributing](CONTRIBUTING.en.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)

## Acknowledgements

AuroraBot uses many excellent open-source projects:

| Project                                                                                                                | Use in AuroraBot                                     |
| ---------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| [LiteLLM](https://github.com/BerriAI/litellm)                                                                          | Model Provider integration and call infrastructure   |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)                                                   | MCP client and tool protocol                         |
| [FastAPI](https://github.com/fastapi/fastapi) / [Uvicorn](https://github.com/encode/uvicorn)                           | Local Panel backend                                  |
| [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) / [Rich](https://github.com/Textualize/rich) | Console and terminal experience                      |
| [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) / [aiosqlite](https://github.com/omnilib/aiosqlite)             | WorldJournal persistence                             |

Thanks also to the other open-source Agent and Bot projects exploring this field. Special thanks to
[MaiBot](https://github.com/MaiM-with-u/MaiBot), whose idea of "digital life" was an important influence on AuroraBot's early thinking.

## License

This project is open source under the [Apache License 2.0](LICENSE).
