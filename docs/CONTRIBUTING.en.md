# Contributing Guide

Thank you for your interest in AuroraBot! This guide will help you get the project running and walk you through the recommended contribution workflow.

## Prerequisites

- **Python** ≥ 3.12, < 3.13
- **uv** (package manager) — [Installation Guide](https://docs.astral.sh/uv/getting-started/installation/)

## Running the Project

```bash
# 1. Clone the repository
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot

# 2. Install dependencies (including dev tools)
uv sync --group dev

# 3. Configure environment variables
cp .env.example .env
# Edit .env and fill in the required API keys, etc.

# 4. Launch
uv run python bot.py
```

## Development Tools

| Command                          | Purpose     |
| -------------------------------- | ----------- |
| `uv run pytest`                  | Run tests   |
| `uv run ruff check src/ tests/`  | Lint code   |
| `uv run ruff format src/ tests/` | Format code |
| `uv run pyright src/`            | Type-check  |

> At minimum, run `pytest` and `ruff check` before submitting a PR to catch obvious regressions.

## Contribution Workflow

We follow a lightweight **branch → PR → merge-and-discard** workflow:

```
dev (latest)
  │
  ├── feat/xxx          ← feature branch
  ├── fix/xxx           ← bugfix branch
  └── refact/xxx        ← refactoring or optimization branch
```

### 1. Branch off the latest `dev`

```bash
git checkout dev
git pull origin dev
git checkout -b feat/my-feature    # or fix/xxx, refact/xxx
```

> Branch prefix conventions:
>
> - **feat/** — New feature
> - **fix/** — Bug fix
> - **refact/** — Code refactoring or optimization (no behavioral changes)

### 2. Develop on your branch

Commit and iterate freely on your local branch. Keep commit messages clear and concise.

### 3. Submit a PR against the `dev` branch

Push your branch to the remote and open a Pull Request targeting the `dev` branch.

### 4. After merge, the branch's mission is complete

Once your PR is merged into `dev`, that branch has served its purpose. **Do not reuse it for further feature development.** You can safely delete it:

```bash
git branch -d feat/my-feature
```

### 5. If additional changes are needed

There are two paths:

- **PR not yet merged** — Mark the PR as **Draft**, continue iterating on the same branch, and switch it back to Ready for review when done.
- **PR already merged** — Repeat the workflow above: branch off the latest `dev` and create a new `feat/`, `fix/`, or `refact/` branch.

> This approach keeps each branch focused on a single responsibility with a clear lifecycle, avoiding the mess of one branch carrying multiple unrelated changes over time.

---

If you have any questions, feel free to open an [Issue](https://github.com/AuroraBot-Dev/AuroraBot/issues).
