# Contributing to AuroraBot

[中文](CONTRIBUTING.md) | [日本語](CONTRIBUTING.ja.md)

Thank you for contributing to AuroraBot. Architecture decisions are captured in RFCs, and code, configuration, tests,
and public documentation are expected to stay consistent.

## Getting started

Python 3.12, Git, and [uv](https://docs.astral.sh/uv/) are required.

```powershell
git clone https://github.com/AuroraBot-Tech/AuroraBot.git
Set-Location AuroraBot
uv sync --group dev
Copy-Item .env.example .env
```

Keep secrets in the local `.env` file or process environment. Never commit secrets, real conversations, model
continuations, workspace events, or runtime logs.

## Design workflow

- `docs/rfc/` is the sole baseline for architecture and public contracts.
- Update or add an RFC before changing module boundaries, AMP/Kernel events, configuration, extension protocols, or
  model-call contracts.
- Small bug fixes, test additions, and semantics-preserving refactors can be submitted directly with verification.
- When documentation changes public behavior, update the Chinese, English, and Japanese entry points together.

## Module boundaries

- Kernel owns events, Task/Agent state, mailboxes, Activities, and causality. It does not choose cognitive content or
  execute Platform effects.
- Agent handlers only read `AgentContext` and return side-effect-free `AgentDecision` values.
- Platform normalizes AMP input and executes `effect.requested`; each result returns to Kernel as a new event.
- `localhost` owns local use cases, while `dashboard` only adapts routes and APIs.
- `utils` cannot depend on upper-layer packages. Shared logging uses `src.utils.log_utils.get_logger()`.

## Branches and pull requests

1. Create a short-lived branch from `dev`; `feat/`, `fix/`, and `refact/` are the recommended prefixes.
2. Keep each PR focused on one reviewable goal and include the corresponding tests and documentation.
3. Target `dev` and describe behavior changes, verification commands, known boundaries, and related RFCs or issues.
4. Merge after CI and review pass, then delete the completed branch.

## Verification

```powershell
# Unified project check
uv run aurora check

# Individual checks when needed
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

Tests must be deterministic and offline. Use fake models, clocks, and MCP implementations; tests must not consume real
credits or require public network services. Bug fixes should cover the failing path first. Event and effect tests should
also verify transaction boundaries, idempotency, and causal parentage.

## Before submitting

- Kernel and Platform boundaries remain intact, and no Provider-private object is written to the workspace.
- Logs include stable diagnostic identifiers without secrets, full prompts, continuations, or sensitive payloads.
- TOML remains the structural source of configuration, and secrets still come only from environment variables.
- READMEs, module documentation, configuration examples, and RFCs do not contradict one another.
- New behavior has tests and `uv run aurora check` passes.

By contributing, you agree to follow the project's [Code of Conduct](../CODE_OF_CONDUCT.md).
