<p align="center">
  <img src=".github/assets/logo.svg" width="112" alt="AuroraBot Logo" />
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
  <a href="docs/INDEX.md"><img src="https://img.shields.io/badge/Docs-repository-315b7d" alt="Documentation" /></a>
  <a href="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml"><img src="https://github.com/AuroraBot-Dev/AuroraBot/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-315b7d" alt="Apache 2.0" /></a>
  <img src="https://img.shields.io/badge/Python-3.12-315b7d?logo=python&logoColor=white" alt="Python 3.12" />
</p>

## What is AuroraBot?

AuroraBot is a Bot framework that provides a "living" runtime for Agents. We are not aiming for a tool-like Agent, but a Bot that persists, forms its own rhythm, and judges and acts autonomously in its environment.

She has her own persona and state, and can connect with people and the outside world when needed. In her world, every message has a medium: your messages arrive through the conversation interface, and external applications can bring events into her world ~

## Design philosophy

### Design everything around the Bot

AuroraBot treats the Bot as the subject of her world, not an interface to be called: she persists, with her own persona, state, and boundaries, and everything is designed around her life. This principle lands in three points in the architecture:

- **She owns the world; each run is an experience**: the Bot has her own world, goals, and memories. Each cognitive run is an episode in her life; chats and tasks are episodes in her life, and when an episode ends, she still exists.
- **Every input has a medium**: user messages arrive as guidance through the conversation interface; application events and MCP reports enter through world sources, tool results return to the current reasoning loop, and scheduled wakeups go to the runtime owner. With autonomous cadence enabled, she can also decide whether to act on world changes.
- **She understands before she decides**: world events and external content do not automatically become the highest command just because they appear. She first understands what happened, then decides to respond, act, or keep observing; the model is only responsible for understanding and judgment, external actions must go through declared Tools, and outcomes return to the reasoning context and are separately archived when action evidence is enabled.

## Quick start

### 1. Clone this repository

You need Python 3.12+, Git, and [uv](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot
uv sync --locked --all-packages
uv run --locked python examples/onboarding/main.py --init
```

Initialization creates missing onboarding assistant files in the separate `build/onboarding` directory without calling models or starting tools.

### 2. Fill in the required configuration

Set `provider`, `model`, and any required `base_url` in `build/onboarding/config/org.aurora.adapter/model/profiles.toml`. Set `AURORA_MODEL_API_KEY` in the root `.env`; `credential` contains only the environment variable name.

### 3. Start from the terminal

```bash
uv run --locked python examples/onboarding/main.py --text "Check my environment and tell me what is missing for the first Aurora startup."
```

The assistant processes this message and exits; real conversations call your configured model. See the [first-run guide](examples/START.md) for continuous conversations, TUI and Panel connections, and [operations](docs/operations.md) for starting the main Bot.

## AIGC

This project contains human-reviewed code written with assistance from generative models.

## Contributing

See [Contributing to AuroraBot](.github/CONTRIBUTING.en.md) and the [AuroraBot documentation](docs/INDEX.md). By contributing, you agree to abide by the project's [Code of Conduct](.github/CODE_OF_CONDUCT.md).

## Acknowledgements

AuroraBot would not exist without many excellent open-source projects:

| Project                                                                                                                | Use in AuroraBot                                   |
| ---------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| [LiteLLM](https://github.com/BerriAI/litellm)                                                                          | Model Provider integration and call infrastructure |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)                                                   | MCP client and tool protocol                       |
| [OpenTUI](https://github.com/anomalyco/opentui) / [Rich](https://github.com/Textualize/rich) | TUI and log display                    |
| [Vue](https://github.com/vuejs/core) / [Vite](https://github.com/vitejs/vite)             | Panel interface and build                           |

We also thank the other open-source Agent/Bot projects exploring this field. Special thanks to [MaiBot](https://github.com/MaiM-with-u/MaiBot), whose "digital life" idea was an important inspiration for AuroraBot's early thinking.

## License

This project is open source under the [Apache License 2.0](LICENSE).
