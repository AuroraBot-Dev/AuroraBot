# AuroraBot

基于 **AuroraBot Core** (Brain + MCP Platform) 的内驱式、自主决策智能体框架 — 文件驱动认知引擎 + 三级联合记忆 + 可插拔 MCP App Server 体系。

## Project

- **Stack**: Python 3.12, LiteLLM, ChromaDB, mem0, MCP SDK (`mcp[cli]>=1.27`)
- **Package manager**: `uv` (lockfile `uv.lock`)
- **Entry points**:
  - `bot.py` — NoneBot (QQ/OneBot 可选 Connector)
  - `python -m src.aurora.main` — Core standalone (不依赖 NoneBot)
- **Config**: `.env` (loaded by `src/config.py`), `apps/config.yml` (per-app MCP 配置)
- **CI**: GitHub Actions — `ruff check`, `ruff format --check`, `pyright src/`, `pytest --cov=src`
- **NoneBot 定位**: Core 不依赖 NoneBot。NoneBot 是 QQ/OneBot 接入的 **可选 Connector**，不是主框架。参见 `docs/reports/nonebot-decoupling-feasibility.md`
- **Runtime version**: `v0.4.0`

## Commands

| Purpose      | Command                                  |
| ------------ | ---------------------------------------- |
| Install deps | `uv sync --group dev` (CI: `--locked`)   |
| Run (NoneBot)| `uv run python bot.py`                   |
| Run (standalone) | `uv run python -m src.aurora.main`   |
| Tests        | `uv run pytest --cov=src`                |
| Lint         | `uv run ruff check src/ tests/`          |
| Format       | `uv run ruff format src/ tests/`         |
| Format check | `uv run ruff format --check src/ tests/` |
| Type check   | `uv run pyright src/`                    |

## Architecture

```
bot.py / src/aurora/main.py   → 入口 (NoneBot / standalone)
src/config.py                 → 中央配置 from .env, path constants, ensure_dirs()
│
├── src/brain/                → Cognitive Engine (CortexForge)
│   ├── kernel/               → Node/Agent/Router 基类, Circuit, FileEventBus, NodeFactory
│   ├── memory/               → L1 (working/FIFO), L2 (episodic/JSON), L3 (semantic/ChromaDB)
│   ├── runtime.py            → 运行时管理：启动/关闭 Circuit + MCP + 事件桥接
│   ├── nodes/                → 认知节点 (topology.yaml 声明)
│   │   ├── agents/           → internalizer, externalizer, memory_consolidator 等
│   │   ├── routers/          → message_preprocessor, command_dispatcher, heartbeat 等
│   │   ├── event_bridge.py   → MCP 事件桥接 (notification → inbox)
│   │   └── self_stream.py    → 自我意识流 (自由联想引擎)
│   ├── ai/                   → LLM gateway (LiteLLM), models, providers
│   ├── prompts/              → 提示词模板
│   └── localhost/            → 交互式控制台 (python -m src.brain.localhost)
│
├── src/platform/             → MCP Host Layer (已迁移完成)
│   └── mcp_kit/              → MCP 平台层
│       ├── server_spec.py    → MCPServerSpec dataclass
│       ├── server_kit.py     → MCP Server 进程生命周期管理
│       ├── client_manager.py → MCP Client 连接 + tools/call + notification
│       ├── amp.py            → AMP envelope (Host-side 兼容层)
│       ├── tool_schema.py    → MCP Tool ↔ OpenAI schema 转换
│       ├── manifest.py       → manifest.yaml MCP 扩展 (可选)
│       └── discovery.py      → apps/config.yml 读取 + 外部 Server 位置无关配置
│
├── src/utils/                → log_utils, json_utils, time_utils
│
├── apps/                     → 内建 MCP 应用
│   ├── aurora-app-diary/     → 日记 (已 MCP 化)
│   ├── aurora-app-clock/     → 时钟/闹钟/定时器 (已 MCP 化)
│   ├── aurora-app-weather/   → 天气查询 (已 MCP 化)
│   └── aurora-app-qq/        → QQ 适配器 (NoneBot 强耦合，建议用户安装)
│
├── tests/                    → pytest suite (当前 220 tests)
└── data/                     → Runtime state: kernel/, memory/, app_data/
```

### AMP 定位（关键原则）

**AMP 是 Host-side 兼容层，不是 MCP Server 协议。** 普通 MCP Server 不需要知道 AMP。AMP 由 Platform 在本地生成，把 MCP 能力翻译为 Brain 统一事件。原生 Aurora App 可额外使用 `aurora/event` notification 主动推送（可选增强）。

### Data flow (Kernel-γ pipeline)

```
External event → inbox/pending/event_*.json
  → message_preprocessor → pipeline/message_queue/*.json
  → internalizer (B→A) → pipeline/internalized/*.json
  → externalizer (A→B) → pipeline/action_queue/*.json
  → command_dispatcher / mcp_tool_dispatcher
```

Nodes communicate exclusively through files (FileEventBus). Topology: `src/brain/nodes/topology.yaml`.

### Runtime 启动顺序

```
start_runtime():
  1. Config.ensure_dirs()
  2. discover_mcp_servers()  从 apps/config.yml 读取
  3. MCPServerKit.start_all()  启动 stdio Server 进程
  4. MCPClientManager.connect_all()  建立 session
  5. MCPClientManager.refresh_tools()  获取工具列表
  6. build_circuit() + circuit.start()  启动 Brain
  7. run_mcp_event_bridge()  启动 MCP → Brain 事件桥接
```

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

- `apps/` 是内建应用目录，用户 MCP Server 位置无关（通过 `apps/config.yml` 的 `command` 配置）
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
