# AuroraBot

基于 **AuroraBot Core** (Brain + MCP Platform) 的内驱式、自主决策智能体框架 — 文件驱动认知引擎 + 三级联合记忆 + 可插拔 MCP App Server 体系。

## Project

- **Stack**: Python 3.12, LiteLLM, ChromaDB, mem0, MCP SDK (`mcp[cli]>=1.27`)
- **Package manager**: `uv` (lockfile `uv.lock`)
- **Entry points**:
  - `bot.py` — Core standalone
- **Config**: `.env` (loaded by `src/config.py`), `apps/config.yml` (per-app MCP 配置)
- **CI**: GitHub Actions — `ruff check bot.py src/ tests/`, `ruff format --check bot.py src/ tests/`, `pyright bot.py src/`, `pytest --cov=src`
- **QQ/OneBot 定位**: 当前仓库不内置 QQ/OneBot Connector；如需接入，应作为外部 MCP App Server 提供。
- **Runtime version**: `v0.4.0`

## Commands

| Purpose      | Command                                  |
| ------------ | ---------------------------------------- |
| Install deps | `uv sync --group dev` (CI: `--locked`)   |
| Run (standalone) | `uv run python bot.py`              |
| Tests        | `uv run pytest --cov=src`                |
| Lint         | `uv run ruff check bot.py src/ tests/`          |
| Format       | `uv run ruff format bot.py src/ tests/`         |
| Format check | `uv run ruff format --check bot.py src/ tests/` |
| Type check   | `uv run pyright bot.py src/`                    |

## Architecture

```
bot.py                        → Core standalone 入口
src/config.py                 → 中央配置 from .env, path constants, ensure_dirs()
│
├── src/runtime.py            → 运行时管理：启动/关闭 Circuit + MCP + 事件桥接
├── src/kernel/               → immutable events, SQLite/object storage, runtime, capability registry
├── src/memory/               → L1 (working/FIFO), L2 (episodic/JSON), L3 (semantic/ChromaDB)
├── src/nodes/                → 自包含认知节点与 MCP event bridge
│   └── cognitive.py          → attention, Gateway/MCP capability, review, reflection, dream
├── src/ai/                   → LLM gateway (LiteLLM), models, providers
├── src/prompts/              → 提示词模板
├── src/localhost/            → 运行时内置交互式控制台
├── src/sandbox/              → 代码沙箱执行环境
│
├── src/platform/             → 全平台兼容层
│   ├── amp.py                → AMP envelope (共享协议，所有适配器共用)
│   └── mcp/                  → MCP 协议适配器 (MCP ↔ AMP)
│       ├── server_spec.py    → MCPServerSpec dataclass
│       ├── server_kit.py     → MCP Server 进程生命周期管理
│       ├── client_manager.py → MCP Client 连接 + tools/call + notification
│       ├── tool_schema.py    → MCP Tool ↔ OpenAI schema 转换
│       ├── manifest.py       → manifest.yaml MCP 扩展 (可选)
│       └── discovery.py      → apps/config.yml 读取 + 外部 Server 位置无关配置
│
├── src/utils/                → log_utils, json_utils, time_utils
│
├── apps/                     → 内建 MCP 应用
│   ├── aurora-app-diary/     → 日记 (已 MCP 化)
│   ├── aurora-app-clock/     → 时钟/闹钟/定时器 (已 MCP 化)
│   └── aurora-app-weather/   → 天气查询 (已 MCP 化)
│
├── tests/                    → pytest suite (当前 214 tests)
└── data/                     → Runtime state: kernel/, memory/, app_data/
```

### AMP 定位（关键原则）

**AMP 是 Host-side 兼容层，不是 MCP Server 协议。** 普通 MCP Server 不需要知道 AMP。AMP 由 Platform 在本地生成，把 MCP 能力翻译为 Brain 统一事件。原生 Aurora App 可额外使用 `aurora/event` notification 主动推送（可选增强）。

### Data flow (Kernel-γ pipeline)

```
External event → input.external → perception → attention → route
  → low-entropy context | fast response | complex Gateway + MCP capability
  → review → outbox → effect/reflection/context frame
```

Nodes communicate through immutable event files and SQLite metadata. Built-in nodes are in `src/nodes/cognitive.py`.

### Runtime 启动顺序

```
start_runtime():
  1. Config.ensure_dirs()
  2. discover_mcp_servers()  从 apps/config.yml 读取
  3. MCPServerKit.start_all()  启动 stdio Server 进程
  4. MCPClientManager.connect_all()  建立 session
  5. MCPClientManager.refresh_tools()  获取工具列表
  6. build_cognitive_runtime() + circuit.start()  启动 Brain
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
