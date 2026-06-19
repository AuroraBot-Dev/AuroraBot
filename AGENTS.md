# AuroraBot

基于 **AuroraBot Core** (Brain + MCP Platform) 的内驱式、自主决策智能体框架 — 文件驱动认知引擎 + 三级联合记忆 + 可插拔 MCP App Server 体系。

## Project

- **Stack**: Python 3.12, LiteLLM, ChromaDB, mem0, MCP SDK (`mcp[cli]>=1.27`)
- **Package manager**: `uv` (lockfile `uv.lock`)
- **Entry point**: `bot.py` (NoneBot) 或规划中的 `src/aurora/main.py` (standalone)
- **Config**: `.env` (loaded by `src/config.py`), `apps/config.yml` (per-app MCP 配置)
- **CI**: GitHub Actions — `ruff check`, `ruff format --check`, `pyright src/`, `pytest --cov=src`
- **NoneBot 定位**: Core 不依赖 NoneBot。NoneBot 是 QQ/OneBot 接入的 **可选 Connector**，不是主框架。参见 `docs/reports/nonebot-decoupling-feasibility.md`

## Commands

| Purpose      | Command                                  |
| ------------ | ---------------------------------------- |
| Install deps | `uv sync --group dev`                    |
| Run (NoneBot)| `uv run python bot.py`                   |
| Tests        | `uv run pytest --cov=src`                |
| Lint         | `uv run ruff check src/ tests/`          |
| Format       | `uv run ruff format src/ tests/`         |
| Format check | `uv run ruff format --check src/ tests/` |
| Type check   | `uv run pyright src/`                    |

## Architecture

```
bot.py / src/main.py     → 入口 (NoneBot / standalone)
src/config.py            → 中央配置 from .env, path constants, ensure_dirs()
│
├── src/brain/           → Cognitive Engine (CortexForge)
│   ├── kernel/          → Node/Agent/Router 基类, Circuit, FileEventBus, NodeFactory
│   ├── memory/          → L1 (working/FIFO), L2 (episodic/JSON), L3 (semantic/ChromaDB)
│   ├── nodes/           → 认知节点 (topology.yaml 声明)
│   │   ├── agents/      → internalizer, externalizer, memory_consolidator 等
│   │   ├── routers/     → message_preprocessor, command_dispatcher (待 MCP 替代), heartbeat 等
│   │   └── event_bridge.py → 旧 drain_events + 新 run_mcp_event_bridge 双轨
│   ├── ai/              → LLM gateway (LiteLLM), models, providers
│   ├── prompts/         → 提示词模板
│   └── localhost/       → 交互式控制台
│
├── src/platform/        → Application Host Layer (迁移中)
│   ├── mcp_kit/         → ★ 新 MCP 平台层 (Phase 1-4 已完成)
│   │   ├── server_spec.py    → MCPServerSpec dataclass
│   │   ├── server_kit.py     → MCP Server 进程生命周期管理
│   │   ├── client_manager.py → MCP Client 连接 + tools/call + 可选 notification
│   │   ├── amp.py            → AMP envelope (Host-side 兼容层, 非 MCP Server 协议)
│   │   ├── tool_schema.py    → MCP Tool ↔ OpenAI schema 转换
│   │   ├── manifest.py       → manifest.yaml MCP 扩展 (可选)
│   │   └── discovery.py      → 内建 apps/ 扫描 + 外部 MCP Server 位置无关配置
│   ├── application_host.py   → 旧 App Host (Phase 7 删除)
│   ├── application_api.py    → 旧 PlatformAPI (Phase 7 删除)
│   ├── app_discovery.py      → 旧扫描 (Phase 7 删除)
│   └── loop.py               → 旧 tick 循环 (Phase 7 删除)
│
├── src/utils/           → log_utils, json_utils, time_utils
│
├── apps/                → ★ 内建应用 (非安装位置)
│   ├── aurora-app-diary/    → 已 MCP 化 (样板), service + mcp_server + runtime 兼容层
│   ├── aurora-app-clock/    → 待 MCP 化, 纯 stdlib, on_tick 需改造
│   ├── aurora-app-weather/  → 待 MCP 化, 轻 HTTP
│   └── aurora-app-qq/       → 建议用户安装 (NoneBot 强耦合)
│
├── tests/               → pytest suite (当前 296 tests)
└── data/                → Runtime state: kernel/, memory/, app_data/
```

### AMP 定位（关键原则）

**AMP 是 Host-side 兼容层，不是 MCP Server 协议。** 普通 MCP Server 不需要知道 AMP。AMP 由 Platform 在本地生成，把 MCP 能力翻译为 Brain 统一事件。原生 Aurora App 可额外使用 `aurora/event` notification 主动推送（可选增强）。

### Data flow (Kernel-γ pipeline)

```
External event → inbox/pending/event_*.json
  → message_preprocessor → pipeline/message_queue/*.json
  → internalizer (B→A) → pipeline/internalized/*.json
  → externalizer (A→B) → pipeline/action_queue/*.json
  → command_dispatcher / (未来) mcp_tool_dispatcher
```

Nodes communicate exclusively through files (FileEventBus). Topology: `src/brain/nodes/topology.yaml`.

## Conventions

### Code style

- **Line length**: 120 (`ruff`), LF endings
- **Quotes**: double quotes preferred (`Q` rule)
- **Imports**: `from __future__ import annotations` everywhere; isort enforced (`I`)
- **Types**: annotations on public functions (`ANN`); `slots=True` on dataclasses; no `Any` (`ANN401` suppressed)
- **No bare except** (`BLE`), no `print` (`T20`), no `datetime.now()` without tz (`DTZ`)
- **Modern Python**: `X | Y` unions, PEP 604; pathlib (`PTH`); simplified constructs (`SIM`)

### Logging

```python
from src.utils.log_utils import get_logger
logger = get_logger("ModuleName")
```
- **ERROR**: functional interruptions, exceptions
- **WARNING**: recoverable anomalies, config fallbacks
- **INFO**: lifecycle events only (start/stop, app register, user-visible results). NOT per-request.
- **DEBUG**: everything else — request handling, cache reads, LLM calls, file I/O
- See `LOGGING.md` for the full policy.

### Singleton pattern

Key services (gateway, memory_manager, app_host) use lazy-init module-level proxies. Init-on-first-access with one INFO line.

### Naming & structure

- `apps/` 是内建应用目录，用户 MCP Server 位置无关（通过 `apps/config.yml` 的 `mcp.command` 配置）
- App namespace: `im.polaris.*` (e.g. `im.polaris.weather`)
- Test files: `tests/test_*.py`, runnable from project root
- MCP tool names: `{package}.{tool_name}` (e.g. `im.polaris.diary.write_diary`)

### Git workflow

- **Base branch**: `dev`
- **Feature branches**: `feat/*`, `fix/*`, `refact/*`
- **PR to `dev`**, merge once, delete branch
- CI auto-tags `vX.Y.Z-alpha.N` on merge to `dev`
- `main` receives releases only

## Notes

- AGENTS.md 自动加载于每次会话。有重构记录请查项目记忆 `refact-platform-mcp-session-state`
- `docs/reports/` 下有多个架构决策文档，处理重构前建议先查阅
