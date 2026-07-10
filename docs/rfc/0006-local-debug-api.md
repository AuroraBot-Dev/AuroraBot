# RFC 0006：本地运行器与开发调试 HTTP API

状态：已接受
日期：2026-07-11

## 背景

最小因果闭环需要可重复的开发入口，但 Dashboard 不是第二个运行时，且 vNext 尚未定义面向最终用户的会话 API。

## 决策

`src/localhost` 提供唯一的本地运行用例，并以 FastAPI 暴露开发调试 API。它只编排 Kernel、已启用节点和 Platform；`dashboard` 如需接入，只能调用该用例。

默认监听 `127.0.0.1`，地址和端口仅由 `config/aurora.toml` 的 `runtime.debug_host` 与 `runtime.debug_port` 定义。生产 profile 不得把该 API 暴露到非 loopback 地址。

API 为：

- `POST /v1/debug/amp`：校验并原子投递 AMP，返回 `202` 与 `message_id`。
- `POST /v1/debug/cycles`：运行一个周期，返回其编号、已接管记录、已调度记录和 Platform 回执数。
- `GET /v1/debug/records/{record_id}`：返回已脱敏的 Kernel record；不存在时返回 `404`。
- `GET /healthz`：返回运行器可用状态。

该 API 仅用于开发和契约测试，不提供最终用户聊天语义、认证、多租户、远程管理或 Dashboard 前端资源。AMP 正文和 SOUL 内容不写入 INFO 日志。

## 验收标准

1. 可通过 API 投递 AMP、推进两个周期并查询到完整因果链。
2. API 不直接修改 Kernel 状态；所有写入均经 localhost 用例和 Kernel API。
3. 非 loopback 监听在生产 profile 启动前失败。

## 迁移影响

旧 `bot.py` 不参与本地运行器；任何最终用户或远程 API 须由后续 RFC 定义。
