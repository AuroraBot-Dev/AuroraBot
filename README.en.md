<p align="center">
  <img src="assets/logo.svg" width="112" alt="AuroraBot Logo" />
</p>

<h1 align="center">AuroraBot</h1>

<p align="center">
  <a href="README.md">中文</a> | <b>English</b> | <a href="README.ja.md">日本語</a>
</p>

<p align="center">
  <em>Give a Bot a life of its own.</em>
</p>

<p align="center">
  <a href="https://github.com/AuroraBot-Dev/AuroraBot"><img src="https://img.shields.io/badge/GitHub-AuroraBot-181717?logo=github" alt="GitHub" /></a>
  <a href="https://www.aurorabot.org/"><img src="https://img.shields.io/badge/Docs-aurorabot.org-315b7d" alt="Documentation" /></a>
  <a href="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml"><img src="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-315b7d" alt="Apache 2.0" /></a>
  <img src="https://img.shields.io/badge/Python-3.12-315b7d?logo=python&logoColor=white" alt="Python 3.12" />
</p>

## What is AuroraBot?

AuroraBot is a Bot framework that provides a "living" runtime for Agents. We are not aiming for a tool-like Agent, but a Bot that persists, forms its own rhythm, and judges and acts autonomously in its environment.

She has her own persona and state, and can connect with people and the outside world when needed. In her world, every message has a medium: even the message you send her must first become an app notification ~

## Design philosophy

### Design everything around the Bot

AuroraBot treats the Bot as the subject of her world, not an interface to be called: she persists, with her own persona, state, and boundaries, and everything is designed around her life. This principle lands in three points in the architecture:

- **She owns the world; a tree is only one of her runs**: the Bot holds an append-only world journal (WorldJournal) and multiple `AgentTree`s. A tree is only one run, not another subject parallel to her; chats, tasks, and delegations are episodes in her life, and when an episode ends, she still exists.
- **Every input has a medium**: any change that affects her must first become a world event. The message you send her must first be committed to her world as `console.input`, and so are application events, MCP reports, tool results, and the passage of time. She is not responding to an interface; she is experiencing her world.
- **She understands before she decides**: a message from a user does not automatically become the highest command just because of its source. She first understands what happened, then decides to respond, act, delegate, or stay quiet; the model is only responsible for understanding and judgment, external actions must go through declared Tools, and outcomes return to her world as new events.

## Quick start

### 1. Clone this repository

You need Python 3.12, Git, and [uv](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot
./scripts/linux/setup.sh
# macOS: ./scripts/macos/setup.command;
# Windows: .\scripts\windows\setup.ps1.
```

`setup.sh` installs aurora into your user tool directory and bootstraps dependencies, personal configuration, and the docs/panel submodules.

### 2. Fill in the required configuration

Fill in the key the default model needs (e.g. `DEEPSEEK_API_KEY`) in `.env`

### 3. Start from the terminal

```bash
aurora start
```

Type a message after startup to chat; use `/help` to discover operations and `/exit` to stop.

## AIGC

This project contains code written with assistance from generative models such as large language models or diffusion models, and it has been reviewed by humans.

## Contributing

See [Contributing to AuroraBot](CONTRIBUTING.en.md) and the [AuroraBot documentation site](https://www.aurorabot.org). By contributing, you agree to abide by the project's [Code of Conduct](CODE_OF_CONDUCT.md).

## Acknowledgements

AuroraBot would not exist without many excellent open-source projects:

| Project                                                                                                                | Use in AuroraBot                                   |
| ---------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| [LiteLLM](https://github.com/BerriAI/litellm)                                                                          | Model Provider integration and call infrastructure |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)                                                   | MCP client and tool protocol                       |
| [FastAPI](https://github.com/fastapi/fastapi) / [Uvicorn](https://github.com/encode/uvicorn)                           | Local Panel backend                                |
| [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) / [Rich](https://github.com/Textualize/rich) | Console and terminal experience                    |
| [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) / [aiosqlite](https://github.com/omnilib/aiosqlite)             | WorldJournal persistence                           |

We also thank the other open-source Agent/Bot projects exploring this field. Special thanks to [MaiBot](https://github.com/MaiM-with-u/MaiBot), whose "digital life" idea was an important inspiration for AuroraBot's early thinking.

## License

This project is open source under the [Apache License 2.0](LICENSE).
