# RFC 0006：本地运行用例与开发调试 HTTP API

状态：已接受
日期：2026-07-11
修订：2026-07-15

## 背景

认知闭环需要可重复的开发入口，但 Dashboard 不是第二个运行时，调试 API 也不是面向最终用户的会话 API。
RFC 0010 将 HTTP 路由适配归入 `src.dashboard`；localhost 继续拥有调试业务用例。

## 决策

`src/localhost` 提供唯一的本地运行用例，编排 Kernel、已启用 Node、scheduler 和 Platform。
`src/dashboard` 使用 FastAPI 暴露开发调试路由，并且只能调用 localhost 公开用例，不得直接操作 Kernel。
应用工厂只由 `src.dashboard.api` 导出；`localhost` 不反向导入或重新导出 Dashboard 路由。

调试服务默认监听 `127.0.0.1`，地址和端口只由 `config/aurora.toml` 的 `runtime.debug_host` 与
`runtime.debug_port` 定义。生产 profile 不得把该服务暴露到非 loopback 地址。

API 为：

- `POST /v1/debug/amp`：校验并原子投递 AMP，返回 `202` 与 `message_id`。
- `POST /v1/debug/cycles`：运行一个周期，返回周期编号、接管记录、调度记录和 Platform 回执数。
- `GET /v1/debug/records/{record_id}`：返回已脱敏 Kernel record；不存在时返回 `404`。
- `GET /v1/debug/status`：返回周期、scheduler、活动 Episode 和 model dispatcher 状态。
- `GET /v1/debug/episodes/{episode_id}`：返回已脱敏 Episode snapshot；不存在时返回 `404`。
- `GET /healthz`：返回运行器可用状态。

该 API 仅用于开发和契约测试，不提供最终用户聊天语义、远程管理或 Dashboard 前端资源。AMP 正文和 SOUL
内容不写入 INFO 日志。Dashboard 聊天 API、鉴权和 WebSocket 由 RFC 0010 单独定义。

## 验收标准

1. 可通过 API 投递 AMP、推进周期并查询完整因果链与 Episode 状态。
2. 路由不直接修改 Kernel 状态；所有写入均经 localhost 用例和 Kernel API。
3. 非 loopback 监听在生产 profile 启动前失败。
4. 调试服务和认知 scheduler 共享同一 `AuroraRuntime`。
