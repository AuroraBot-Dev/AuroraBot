# Contributing to AuroraBot

<a href="CONTRIBUTING.md">中文</a> | <b>English</b> | <a href="CONTRIBUTING.ja.md">日本語</a>

AuroraBot is not aiming for a tool-like Agent, but a Bot that persists, develops her own rhythm, and judges and acts within her own world. We want to explore not just "how to plug in a model," but how she keeps working, acts reliably, and lets people understand why she does what she does.
Whether you bring a bug fix, a more natural introduction, an MCP application, or a runtime improvement, you are welcome.

## Find your entry point

- **First contribution**: fix documentation, add tests, or pick a small, well-bounded issue.
- **Application developers**: connect MCP services or plugins to provide capabilities for AuroraBot.
- **Runtime developers**: improve ReAct execution, model adapters, MCP integration, or the local interaction experience.
- **Design participants**: discuss use cases, public contracts, and module boundaries in Issues or Discussions.

If you are not sure where to start, describe the experience you want to improve in a Discussion or an Issue first.

## Prepare your development environment

### 1. Clone this repository

You need Python 3.12+, Git, and [uv](https://docs.astral.sh/uv/); CI verifies Python 3.12 / 3.13.
TUI, Panel and engineering scripts additionally need the [Node.js](https://nodejs.org/) and [pnpm](https://pnpm.io/) versions declared in [package.json](../package.json) and [.node-version](../.node-version). Run `pnpm install --frozen-lockfile` before development checks.

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

The assistant processes this message and exits; real conversations call your configured model. See the [first-run guide](../examples/START.md) for continuous conversations, TUI and Panel connections, and [operations](../docs/operations.md) for starting the main Bot.

Running tests and static checks does not require real model keys. Keys live only in the local `.env` or the process environment; never commit keys, real conversations, full model replies, workspace events, uploaded files, or run logs.

## Before making changes

For changes to public contracts, persistence, or module boundaries, identify the Bot use case, invariants, and verification method. See [AGENTS.md](../AGENTS.md) for development constraints and the [system overview](../docs/aurorabot-design-v0.2.3.md) for component responsibilities. Discuss larger designs in Issues or Discussions.

Documentation describes current usage, capabilities, and limits. Record changes in [docs/CHAGELOG.md](../docs/CHAGELOG.md). Simplified Chinese is authoritative; keep corresponding translations in sync.

## Keep the loop closed

While contributing code, hold the boundaries that keep AuroraBot reliable:

- The model decides, the runtime executes: assistant may only reply or request tools; real external effects run only through the Tool contract, and plain model text is not an effect.
- Each agent instance has one AgentRuntime owner; conversations, cadence and scheduled wakeups submit guidance to that same owner.
- Execution dependencies follow `bot → agent → control → core`; `aurora_adapter` connects models and MCP, and `aurora_config` declares configuration. CLI, API and interfaces reuse backend execution semantics.
- Structural configuration stays in TOML; keys keep coming only from environment variables.
- `aurora_logging` configures shared logging, obtained through `logging.getLogger(__name__)`; never record full prompts, model replies, or sensitive payloads.

For the fuller maintainer boundaries, see `AGENTS.md` at the repository root.

## AIGC

AuroraBot welcomes AI-assisted development, but generated content is bound by the same project boundaries and gets no exemption just because it was "written by AI":

- **Must be verifiable**: code generated or heavily modified by AI must pass all of `aurora check --full` and come with offline, deterministic, repeatable tests;
- **Must be understood and owned**: you must read every generated line, be able to explain its behavior, and take responsibility for its correctness and security;
- **Must respect boundaries**: generated code keeps the existing dependency direction and contracts, introducing no parallel run model or bypass around the closed loop;
- **No masking quality**: do not use lint ignores to hide generated complexity; as a rule, no single file exceeds 600 lines;
- **Chinese text is authoritative**: user-facing copy is authoritative in Simplified Chinese, with no "experimental, refactoring, legacy, migration" narratives and no invented capabilities, APIs, or sample data;
- **Source and safety**: do not introduce code of unknown origin or incompatible licenses, and do not generate or commit keys, real sessions, or private data;
- **Disclose honestly**: state in the Pull Request description which parts were generated or assisted by AI, so reviewers can focus.

Consequences of violations:

- PRs that violate the above are sent back for revision or rewriting of the affected parts;
- PRs that skip `aurora check` without explanation are not merged;
- Repeated or severe violations (e.g. leaking keys, faking test results, bypassing security or architecture boundaries) lead to the PR being closed, a maintainer record, and possibly restricted future contributions.

## Submit your work

1. Create a short-lived branch from `main`; use `feat/<name>` for features, and `fix/` or `refact/` for fixes or refactoring.
2. Keep each Pull Request focused on one reviewable goal, with matching tests and documentation.
3. Set `main` as the merge target and describe behavioral changes, verification results, and related Issues.
4. Wait for CI and review, then delete the finished branch.

## Verification

Run the unified check before submitting:

```powershell
pnpm exec uv run --locked aurora check
```

Depending on the verification scope, run separately:

```powershell
pnpm exec uv run --locked pytest packages/aurora_agent/tests/unit/test_agent_runtime.py -q
pnpm exec uv run --locked aurora check --full
pnpm exec uv run --locked aurora check --test --coverage
uv run --locked ruff check .
uv run --locked ruff format --check .
pnpm typecheck
```

Install development dependencies with `uv sync --locked --all-packages` and `pnpm install --frozen-lockfile`.
Package tests live in `packages/<package>/tests/unit` and `tests/contract`; cross-package contracts live in root `tests/contract`, and process/integration tests in `tests/e2e`. Shared fixtures live in `tests/fixtures` and root `conftest.py`.
Default checks run fast boundary tests; `--full` and `--coverage` use the full test scope. CI runs `--full`; explicit coverage checks have a 20% minimum. This is a floor, not a target for deleting tests.
Prefer behavior, boundary, and recovery tests over duplicate cases, tests of test helpers, or assertions added only for coverage.

Tests must be offline, deterministic, and repeatable. Models, clocks, and MCP use fakes; no real quota is consumed and no public network is needed. Bug fixes should cover the original failure path; event and effect tests should also verify transactional boundaries, idempotency, and execution identity associations.

## Pre-submission checklist

- Users can understand the behavioral difference from the docs or tests.
- New behavior does not bypass the closed loop between model decisions, Tool execution, and result feedback.
- Configuration, documentation, and tests are consistent.
- Logs and test fixtures contain no real keys, sessions, or private data.
- `aurora check` passes, or the Pull Request clearly explains what could not be run.

By contributing, you agree to abide by the project's [Code of Conduct](CODE_OF_CONDUCT.md).
