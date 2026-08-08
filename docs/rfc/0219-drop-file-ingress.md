# 0219：废弃外部 AMP 文件摄入通道——inbox/archive 目录移除

状态：已接受
日期：2026-08-08
来源：文件摄入通道（inbox/*.json → archive/inbox/ 分类）在实际运行中无生产者；所有摄入均经 submit_amp SQLite 直连
先决条件：RFC 0200（外部 AMP 摄入协议）、0210（最小 engine 重写，保留文件通道）、0218（面板后端收敛摄入通道）

## 问题

RFC 0210 保留了外部 AMP 文件摄入协议：外部生产者写临时文件再原子改名放入 `data/engine/inbox/*.json`，
engine 扫描摄入并分类移入 `data/engine/archive/inbox/{accepted,rejected,duplicate}`。

实际运行中该通道**没有生产者**：ops 面板（console `/say`、`POST /messages`）、MCP 平台与工具回执全部经
`submit_amp` → `persist_amp` → `enqueue_inbox` SQLite 直连（RFC 0218 收拢了外部输入入口）。
`data/engine/inbox/` 与 `archive/` 常年为空，形成目录冗余与无用的轮询分支（`has_work` 文件 glob）。

## 决定

1. **废弃文件摄入协议**：删除 `ingress.py` 的 `ingest_ready`/`_ingest_amp_file`/`_archive_inbox` 与
   engine 的 `_inbox`/`_archive` 目录创建及 `has_work` 文件扫描分支；`pump` 不再返回 `ingested_event_ids`。
2. **`persist_amp` 与 `inbox_events` 表保留**：`inbox_events` 是防抖批次与 triage 输入的核心表（RFC 0209），
   摄入路径不变（`submit_amp` → `enqueue_inbox`），仅移除文件形态的中间载体。
3. **工作区收敛为 `data/engine/process/runtime.sqlite3`**：engine 不再创建 `inbox/` 与 `archive/`；
   既有目录与文件不再读取（不迁移、不清理，由运维删除）。
4. **替换 RFC 0210 中"外部 AMP 文件摄入保留"条款**（0210 §"外部 AMP 文件摄入保留（platform 写 JSON → engine 读）"）。

## 结果

- engine 工作区单一化：只读 `process/runtime.sqlite3`，无文件投递箱与分类归档。
- `has_work`/`pump` 热路径少一次目录扫描分支。
- 外部 AMP 摄入协议统一为 `submit_amp`（SQLite 直连），与 RFC 0218 面板入口收敛一致。

## 兼容性

- `inbox_events` 表结构、`submit_amp` 契约、`pump` 返回键（除 `ingested_event_ids`）不变。
- 既有 `data/engine/inbox|archive` 遗留文件不再被读取；不影响启动（无拒绝逻辑）。
- 测试：删除文件摄入用例；engine 摄入/幂等/工具回执用例保留（走 SQLite 直连）。
