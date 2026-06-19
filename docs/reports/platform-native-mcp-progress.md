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

## Phase 1：

| 项目 | 内容 |
|------|------|
| 状态 | 待开始 |
| 开始日期 | — |
| 改动摘要 | 新增 `mcp_kit` 包、AMP 模型、依赖 |
| 验证结果 | — |

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
