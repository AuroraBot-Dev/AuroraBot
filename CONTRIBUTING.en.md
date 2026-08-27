# Contributing to AuroraBot

<a href="CONTRIBUTING.md">中文</a> | <b>English</b> | <a href="CONTRIBUTING.ja.md">日本語</a>

AuroraBot is not aiming for a tool-like Agent, but a Bot that persists, develops her own rhythm, and judges and acts within her own world. We want to explore not just "how to plug in a model," but how she keeps working, acts reliably, and lets people understand why she does what she does.
Whether you bring a bug fix, a more natural introduction, an MCP application, or a runtime improvement, you are welcome.

## Find your entry point

- **First contribution**: fix documentation, add tests, or pick a small, well-bounded issue.
- **Application developers**: start from the built-in Clock app and connect new MCP capabilities to AuroraBot.
- **Runtime developers**: improve AgentTree, the engine, the model gateway, MCP integration, or the local interaction experience.
- **Design participants**: propose RFCs for public contracts and module boundaries, and drive discussion with executable acceptance criteria.

If you are not sure where to start, describe the experience you want to improve in a Discussion or an Issue first.

## Prepare your development environment

### 1. Clone this repository

You need Python 3.12 (recommended; newer versions are not fully verified), Git, and [uv](https://docs.astral.sh/uv/).
Docs or panel development additionally needs [Node.js](https://nodejs.org/) and [pnpm](https://pnpm.io/).

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

Running tests and static checks does not require real model keys. Keys live only in the local `.env` or the process environment; never commit keys, real conversations, full model replies, workspace events, uploaded files, or run logs.

## Before making changes

AuroraBot records design decisions with long-term impact in RFCs. Update or add an RFC under `docs/rfc/` for changes to:

- module responsibilities or dependency direction;
- AgentTree, delegation, and tool receipt contracts;
- TOML configuration, extension protocols, or model call contracts;
- behavior that changes platform composition, process entry points, or persistence semantics.

Small bug fixes, test additions, copy improvements, and refactors that do not change public semantics can be submitted directly. When public documentation changes, update the Chinese, English, and Japanese entry points together.

The current runtime, package boundaries, and process composition follow the single design baseline [RFC 0300](docs/rfc/0300-unified-architecture-and-contracts.md).

## Keep the loop closed

While contributing code, hold the boundaries that keep AuroraBot reliable:

- The model decides, the runtime executes: assistant may only reply or request tools; real external effects run only through the Tool contract, and plain model text is not an effect.
- Delegation is a tree operation: `aur.agent.delegate` is an ordinary visible Tool that the engine interprets to spawn a child; when the child finishes, the parent resumes with the tool result.
- The engine owns the full hot path; concrete model, tool, and memory implementations are injected through contracts Ports, and nodes never call the model gateway or platform clients directly.
- Structural configuration stays in TOML; keys keep coming only from environment variables.
- Shared logging goes through `src.utils.logging.get_logger()` and never records full prompts, model replies, or sensitive payloads.

For the fuller maintainer boundaries, see `AGENTS.md` at the repository root.

## AIGC

AuroraBot welcomes AI-assisted development, but generated content is bound by the same project boundaries and gets no exemption just because it was "written by AI":

- **Must be verifiable**: code generated or heavily modified by AI must pass all of `aurora check` and come with offline, deterministic, repeatable tests;
- **Must be understood and owned**: you must read every generated line, be able to explain its behavior, and take responsibility for its correctness and security;
- **Must respect boundaries**: generated code keeps the existing dependency direction and contracts, introducing no parallel run model or bypass around the closed loop;
- **No masking quality**: do not use lint ignores to hide generated complexity; as a rule, no single file exceeds 600 lines;
- **No replacing the base**: base code such as `packages/@core` in the panel submodule is not accepted as wholesale AI replacement;
- **Chinese text is authoritative**: user-facing copy is authoritative in Simplified Chinese, with no "experimental, refactoring, legacy, migration" narratives and no invented capabilities, APIs, or sample data;
- **Source and safety**: do not introduce code of unknown origin or incompatible licenses, and do not generate or commit keys, real sessions, or private data;
- **Disclose honestly**: state in the Pull Request description which parts were generated or assisted by AI, so reviewers can focus.

Consequences of violations:

- PRs that violate the above are sent back for revision or rewriting of the affected parts;
- PRs that skip `aurora check` without explanation are not merged;
- Repeated or severe violations (e.g. leaking keys, faking test results, bypassing security or architecture boundaries) lead to the PR being closed, a maintainer record, and possibly restricted future contributions.

## Submit your work

1. Create a short-lived branch from `dev`, preferably with a `feat/`, `fix/`, or `refact/` prefix.
2. Keep each Pull Request focused on one reviewable goal, with matching tests and documentation.
3. Set `dev` as the merge target and describe user-visible or behavioral changes, verification commands, known boundaries, and related RFCs/Issues.
4. Wait for CI and review, then delete the finished branch.

## Verification

Run the unified check before submitting:

```powershell
aurora check
```

To narrow the scope, run separately:

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

Tests must be offline, deterministic, and repeatable. Models, clocks, and MCP use fakes; no real quota is consumed and no public network is needed. Bug fixes should cover the original failure path; event and effect tests should also verify transactional boundaries, idempotency, and causal parent-child relationships.

## Pre-submission checklist

- Users can understand the behavioral difference from the docs or tests.
- New behavior does not bypass the closed loop between model decisions, Tool execution, and world commits.
- Configuration, README, module docs, tests, and RFCs do not contradict each other.
- Logs and test fixtures contain no real keys, sessions, or private data.
- `aurora check` passes, or the Pull Request clearly explains what could not be run.

By contributing, you agree to abide by the project's [Code of Conduct](CODE_OF_CONDUCT.md).
