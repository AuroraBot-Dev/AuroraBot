# Contributing to AuroraBot

[简体中文](CONTRIBUTING.md) · [日本語](CONTRIBUTING.ja.md)

Contributions to documentation, bug fixes, tools, interfaces and runtime behavior are welcome. Discuss substantial contract or architecture changes in an Issue or Discussion first, including the use case, invariants and validation plan. Follow the [code of conduct](CODE_OF_CONDUCT.md).

## Development environment

Install Python 3.12+, uv, and the pnpm and Node.js versions in [package.json](../package.json) and [.node-version](../.node-version):

```bash
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot
uv sync --locked --all-packages
pnpm install --frozen-lockfile
pnpm exec uv run --locked aurora check
```

To run a Bot, follow the [onboarding guide](../examples/START.md). Checks use fake models or simulated transports and do not require model credentials. Do not call real providers without explicit authorization. Credentials belong in environment variables or a local `.env`, never in TOML, ctx, snapshots or logs.

## Code and package boundaries

[AGENTS.md](../AGENTS.md) and the [development guide](../docs/development.md) contain the full rules, maintained in Simplified Chinese.

- Use Chinese for comments, docstrings and commit messages; describe current responsibilities and behavior.
- Keep the execution direction `bot → agent → control → core`. Use `aurora_adapter` for model/MCP integration and `aurora_config` for configuration.
- Core provides mechanisms, not model or business control. CLI, API and interfaces reuse backend execution semantics.
- Public IDs follow `<namespace>:<domain>/<local_path>` and belong to their defining package. Update configuration, consumers, tests and documentation with interface changes.
- TOML is the persistent configuration source. Runtime overrides do not write back automatically. Restoring snapshots does not resume execution or replay unfinished tool actions.
- Package tests live in `packages/<package>/tests/unit` or `tests/contract`; cross-package tests live in root `tests/contract` and `tests/e2e`.

## Validation and pull requests

1. Branch from current `main`; use `feat/<name>` for features.
2. Check the working tree and index before starting. Make small commits containing only relevant changes.
3. Run focused checks first and full checks for contract, lifecycle or configuration changes.
4. Record changes, validation results and the distinct value of added tests in [docs/CHAGELOG.md](../docs/CHAGELOG.md).
5. Open a PR against `main`, explain behavior and verification, and wait for CI and review. Do not commit features directly to `main`.

```bash
pnpm exec uv run --locked aurora check
pnpm exec uv run --locked aurora check --full
uv build --all-packages --wheel --out-dir build/wheels
pnpm --filter @aurorabot/panel build
```

The default check covers formatting, linting, types and fast boundary tests. `--full` adds all Python, frontend, native terminal and integration tests; `--coverage` also uses the full scope. CI runs full checks on Python 3.12 / 3.13 and builds all wheels and Panel.

Prefer existing tests that can demonstrate a real defect over redundant coverage. Never remove assertions, relax expectations or skip checks to hide failures. When expanding tests, measure complete command wall time in the same installed environment: target at most 15 seconds for default checks and 60 seconds for full checks. Documentation-only changes need link and diff checks. Distribution or dependency changes also require clean wheel installation checks.

README.md and AGENTS.md changes follow the project's user-confirmation rule. Technical documentation is authoritative in Simplified Chinese; keep English and Japanese community entry points aligned.

## AI-assisted contributions

AI assistance is welcome. Contributors must understand generated content, explain its behavior and take responsibility for correctness. Disclose the scope of assistance in the PR, respect package boundaries and licensing, and report only verification actually performed. Generated content does not exempt a contribution from checks. Reviewers may request corrections; serious or repeated violations follow community rules.

Remove secrets, real conversations, complete model responses, uploads and private runtime data before submitting. Ordinary regression tests must not consume model credits.
