# AuroraBot 平台层原生 MCP 重构 — 迁移进度

> 跟踪每个阶段的执行状态、验证结果和剩余风险。

---

## Phase 0：建基线 ✅

| 项目 | 日期 |
|------|------|
| 完成日期 | 2026-06-19 |
| 当前分支 | `refact/platform` |

### 基线检查结果

| 命令 | 结果 |
|------|------|
| `ruff check src/ tests/` | All checks passed |
| `ruff format --check src/ tests/` | 77 files already formatted |
| `pyright src/` | 0 errors, 0 warnings |
| `pytest --cov=src` | 243 passed, 52% cov |

### 旧接口依赖扫描

扫描命令：

```powershell
rg -n "ApplicationHost|PlatformAPI|ApplicationProtocol|AppEvent|CommandSpec|invoke_command|list_command_specs|drain_events|command_dispatcher|action_queue" src tests apps
```

分类归档见 `reports/phase0-dependency-scan.md`。

### 剩余风险

- 无新增风险，基线已锁定。
- 将保留旧路径至 Phase 7 清理。

---

## Phase 1：新增 MCP 基础设施 ✅

| 项目 | 内容 |
|------|------|
| 完成日期 | 2026-06-19 |
| 开始日期 | 2026-06-19 |
| 改动摘要 | 新增 `mcp_kit` 包（6 文件）、AMP 模型、mcp SDK 依赖 |
| 验证结果 | ruff ✅, pyright ✅ (0 errors), pytest ✅ (270 passed, 55% cov) |

### 新增文件

| 文件 | 职责 |
|------|------|
| `src/platform/mcp_kit/__init__.py` | 包入口 |
| `src/platform/mcp_kit/server_spec.py` | MCPServerSpec dataclass + 约束验证 |
| `src/platform/mcp_kit/amp.py` | AMP envelope：build/parse/convert/legacy 桥接 |
| `src/platform/mcp_kit/tool_schema.py` | MCP Tool → OpenAI schema / prompt text 转换 |
| `src/platform/mcp_kit/manifest.py` | manifest.yaml MCP 扩展读取 |
| `src/platform/mcp_kit/discovery.py` | 扫描 apps/ + config.yml 构建 MCPServerSpec 列表 |
| `tests/test_mcp_amp.py` | 18 个测试：server_spec、AMP、tool_schema |
| `tests/test_mcp_discovery.py` | 9 个测试：manifest、_build_spec、discovery |

### 新增依赖

- `mcp[cli]>=1.27,<2` → 已安装 `mcp==1.28.0`

### 剩余风险

- 旧平台层完全保留（双轨并行）
- MCP Server 进程管理（server_kit.py）和 Client 连接管理（client_manager.py）待 Phase 2

---

## Phase 2：

| 项目 | 内容 |
|------|------|
| 状态 | 待开始 |

---

## Phase 3：

| 项目 | 内容 |
|------|------|
| 状态 | 待开始 |

---

## Phase 4：

| 项目 | 内容 |
|------|------|
| 状态 | 待开始 |

---

## Phase 5：

| 项目 | 内容 |
|------|------|
| 状态 | 待开始 |

---

## Phase 6：

| 项目 | 内容 |
|------|------|
| 状态 | 待开始 |

---

## Phase 7：

| 项目 | 内容 |
|------|------|
| 状态 | 待开始 |

---

## 备注

- 重构指南文档：`docs/reports/platform-native-mcp-refactor-guide.md`
- 研究报告文档：`docs/reports/app-platform-mcp-migration.md`
- 不可变边界：Brain 核心（FileEventBus、记忆系统、节律环路）保持不变
