# Contributing to AuroraBot

[中文](CONTRIBUTING.md) | [日本語](CONTRIBUTING.ja.md)

AuroraBot explores more than connecting an application to a model. It asks how an Agent can keep working, act reliably,
and help people understand why it acted. Bug fixes, clearer writing, MCP applications, and runtime improvements are all
welcome.

## Find your starting point

- **First contribution:** improve documentation, add tests, or pick a small issue with a clear boundary.
- **Application developer:** use the built-in Clock application as a starting point for a new MCP capability.
- **Runtime developer:** improve Agents, Kernel, the model gateway, Platforms, or the local experience.
- **Design contributor:** propose public contracts and boundaries through an RFC with executable acceptance criteria.

If you are unsure where to begin, open a Discussion or Issue describing the experience you want to improve.

## Prepare the development environment

You need Python 3.12 (recommended; higher versions are not fully verified), Git, and [uv](https://docs.astral.sh/uv/).

```powershell
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
Set-Location AuroraBot
uv sync --group dev
Copy-Item .env.example .env

# Add keys to .env and load it explicitly when running a real model
uv run --env-file .env aurora
```

Tests and static checks do not require real model keys. Keep secrets in the local `.env` file or process environment.
Never commit secrets, real conversations, model continuations, workspace events, uploads, or runtime logs.

## Before changing code

AuroraBot uses RFCs for decisions that shape the project over time. Update or add an RFC under `docs/rfc/` before
changing:

- module responsibilities or dependency direction;
- AMP, Task, Agent, Activity, or effect-event contracts;
- TOML configuration, extension protocols, or model-call contracts;
- Platform composition, process entry, or persistence semantics.

Small bug fixes, tests, writing improvements, and refactors that preserve public behavior can be submitted directly.
When public documentation changes, keep the Chinese, English, and Japanese entry points in sync.

The runtime, package boundaries, and process composition follow
[RFC 0200](rfc/0200-agent-centered-runtime.md).

## Keep the loop intact

A few boundaries make AuroraBot's actions reliable:

- Agent handlers read `AgentContext` and return `AgentDecision`; they never call a Provider or Platform client directly.
- Platforms execute external effects and return outcomes as new events. Ordinary model text is not an effect.
- Kernel owns events, state, mailboxes, Activities, and causal records, but not cognitive content.
- Structural configuration remains in TOML, while secrets continue to come only from environment variables.
- Shared logging uses `src.utils.logging.get_logger()` and excludes full prompts, continuations, and sensitive payloads.

See the root `AGENTS.md` for the complete maintainer boundaries.

## Submit an improvement

1. Create a short-lived branch from `dev`; `feat/`, `fix/`, and `refact/` are recommended prefixes.
2. Keep each Pull Request focused on one reviewable outcome and include matching tests and documentation.
3. Target `dev` and explain the user-visible or behavioral change, verification, known limits, and related RFCs or issues.
4. Merge after CI and review pass, then delete the completed branch.

## Verification

Run the unified check before submitting:

```powershell
uv run aurora check
```

Use individual checks when narrowing the scope:

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

Tests must be offline, deterministic, and repeatable. Use fake models, clocks, and MCP implementations rather than real
credits or public services. Bug fixes should cover the original failure path. Event and effect tests should also verify
transaction boundaries, idempotency, and causal parentage.

## Before submitting

- A reader can understand the behavioral difference from documentation or tests.
- New behavior preserves the loop between Agent, Kernel, and Platform.
- Configuration, READMEs, module documentation, tests, and RFCs do not contradict one another.
- Logs and fixtures contain no real secrets, conversations, or private data.
- `uv run aurora check` passes, or the Pull Request clearly states what could not be run.

By contributing, you agree to follow the project's [Code of Conduct](../CODE_OF_CONDUCT.md).
