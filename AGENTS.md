# AuroraBot

基于 NoneBot2 的内驱式、自主决策智能体框架 — 文件驱动认知引擎 + 三级联合记忆 + 可插拔 App 插件体系。

## Project

- **Stack**: Python 3.12, NoneBot2 + OneBot V11, LiteLLM, ChromaDB, mem0
- **Package manager**: `uv` (lockfile `uv.lock`)
- **Entry point**: `bot.py` → NoneBot driver → `src/main.py` (startup/shutdown hooks)
- **Config**: `.env` (loaded by `src/config.py`), `apps/config.yml` (per-app)
- **CI**: GitHub Actions — `ruff check`, `ruff format --check`, `pyright src/`, `pytest --cov=src`

## Commands

| Purpose      | Command                                  |
| ------------ | ---------------------------------------- |
| Install deps | `uv sync --group dev`                    |
| Run          | `uv run python bot.py`                   |
| Tests        | `uv run pytest --cov=src`                |
| Lint         | `uv run ruff check src/ tests/`          |
| Format       | `uv run ruff format src/ tests/`         |
| Format check | `uv run ruff format --check src/ tests/` |
| Type check   | `uv run pyright src/`                    |

## Architecture

```
bot.py                   → NoneBot entry, loads pyproject.toml plugins
src/main.py              → Startup/shutdown: launches runtime + console control loop
src/config.py            → Central config from .env, path constants, ensure_dirs()
│
├── src/brain/           → Cognitive Engine (CortexForge)
│   ├── kernel/          → Node/Agent/Router base classes, Circuit orchestrator, FileEventBus, NodeFactory
│   ├── memory/          → UnifiedMemoryManager: L1 (working/FIFO), L2 (episodic/JSON), L3 (semantic/ChromaDB)
│   ├── nodes/           → Cognitive nodes defined in topology.yaml
│   │   ├── agents/      → internalizer, externalizer, memory_consolidator, (disabled: action_planner, impulse_gate, polaris)
│   │   └── routers/     → message_preprocessor, command_dispatcher, heartbeat_generator, timer_scheduler, switch_router, merge_router, broadcast_router, dead_letter_router, metrics_collector
│   ├── ai/              → LLM gateway (LiteLLM), model definitions, provider registry
│   ├── prompts/         → Prompt templates (INTERNALIZER.md, EXTERNALIZER.md, SOUL.md, GATE.md, …)
│   └── localhost/       → Interactive console shell + control commands (say, emit, invoke, memtest)
│
├── src/platform/        → Application Host Layer
│   ├── application_host.py  → App registry, command dispatch, event queue
│   ├── application_api.py   → PlatformAPI for bidirectional app ↔ host communication
│   ├── app_discovery.py     → Scans apps/ for manifests
│   ├── manifest.py          → manifest.yaml parser & schema
│   └── loop.py              → Async app frame loop (APP_FRAME_INTERVAL)
│
├── src/utils/           → log_utils (get_logger, Rich console + rotating file), json_utils, time_utils
│
├── apps/                → Pluggable Apps (each has manifest.yaml + runtime.py)
│   ├── aurora-app-qq/
│   ├── aurora-app-weather/
│   ├── aurora-app-clock/
│   └── aurora-app-diary/
│
├── tests/               → pytest suite (test_gateway, test_memory, test_circuit, test_node_factory, …)
└── data/                → Runtime state: kernel/ (inbox, pipeline, heartbeat, rhythm), memory/ (chroma, episodes)
```

### Data flow (Kernel-γ pipeline)

```
External event → inbox/pending/event_*.json
  → message_preprocessor → pipeline/message_queue/*.json
  → internalizer (B→A: JSON → first-person narrative) → pipeline/internalized/*.json
  → externalizer (A→B: narrative → JSON action) → pipeline/action_queue/*.json
  → command_dispatcher → PlatformAPI command invocation
```

Nodes communicate exclusively through files (FileEventBus). The topology is declared in `src/brain/nodes/topology.yaml` as a graph of `watch` (glob subscriptions) and `emit` (output paths).

## Conventions

### Code style

- **Line length**: 120 (`ruff`), LF endings
- **Quotes**: double quotes preferred (flake8-quotes `Q` rule active)
- **Imports**: `from __future__ import annotations` in every file; isort enforced (`I`)
- **Types**: mandatory annotations on public functions (`ANN` rules); `slots=True` on dataclasses; no `Any` annotations (`ANN401` ignored only because suppressed)
- **No bare except** (`BLE`), no `print` (`T20`), no `datetime.now()` without tz (`DTZ`)
- **Modern Python**: `X | Y` unions, PEP 604; pathlib (`PTH`); simplified constructs (`SIM`)

### Logging

```python
from src.utils.log_utils import get_logger
logger = get_logger("ModuleName")
```

- **ERROR**: functional interruptions, exceptions
- **WARNING**: recoverable anomalies, config fallbacks
- **INFO**: lifecycle events only (start/stop, app register, user-visible results). NOT per-request or per-event.
- **DEBUG**: everything else — request handling, cache reads, LLM calls, timing, file I/O
- See `LOGGING.md` for the full policy.

### Singleton pattern

Key services (gateway, memory_manager, app_host) use lazy-init module-level proxies. Init-on-first-access with one INFO line; sub-component init uses DEBUG.

### Naming & structure

- `src/` is the NoneBot plugin dir (configured in `pyproject.toml`)
- App packages use `im.polaris.*` namespace (e.g. `im.polaris.qq`, `im.polaris.weather`)
- Command names: `{package}.{command_name}` (e.g. `im.polaris.qq.send_message`)
- Test files: `tests/test_*.py`, runnable from project root with `uv run pytest`

### Git workflow

- Base branch: `dev`
- Feature branches: `feat/*`, `fix/*`, `refact/*`
- PR to `dev`, merge once, delete branch
- CI auto-tags `vX.Y.Z-alpha.N` on merge to `dev`
- `main` receives releases only

## Notes

-
