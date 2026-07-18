# RFC 0010：Dashboard 聊天适配与本地聊天室

状态：已接受
日期：2026-07-15

## 背景

RFC 0009 提供常驻无头循环；AuroraBot 还需要一个使用 Vue、HTTP、WebSocket、SQLite 与附件流程的本地聊天
入口，并且不能产生第二个 Kernel 或让路由绕过 localhost。

本 RFC 部分取代 RFC 0006 将 FastAPI 路由放在 `src.localhost` 的决定，并部分取代 RFC 0009 的无头默认
入口。调试用例仍由 localhost 拥有；HTTP 与 WebSocket 适配位于 `src.dashboard`。

## 决策

`src.dashboard` 只提供 FastAPI 路由、鉴权依赖、WebSocket 连接与协议适配，并且只调用
`src.localhost` 公开用例。账号、会话、消息、附件、历史查询、Bot 投递和回复持久化属于 localhost。
Dashboard 不得直接读写 Kernel、工作区或 Platform client。

`bot.py` 默认在同一进程内启动唯一 `AuroraRuntime`、认知循环和 Dashboard Uvicorn server；
`--headless` 保留无 HTTP 的常驻模式。Dashboard 固定为 loopback 服务，地址、端口、SQLite、上传限制、
会话期限、允许 Origin 与 Bot 身份均来自 TOML。

聊天室保留注册、登录、一对一私聊、历史、增量同步、在线状态和附件。登录令牌为随机 opaque bearer
token，服务端只持久化令牌摘要。内建 Bot 用户不可登录或删除，身份由 TOML 配置且启动时幂等创建。

发给普通用户的消息只经过聊天室用例。发给 Bot 的文本先持久化，再成为普通 `message.received` AMP；
session 使用 `dashboard:user:<id>`。根事件声明回复能力，Node 只能看到与当前输入通道对应的发布工具。
Dashboard 回复效果成功后才持久化 Bot 消息并通过 WebSocket 推送。当前每条用户消息是独立 Episode，
不注入跨消息历史。发给 Bot 的附件只持久化，并产生确定性的“不支持读取附件”回复，不调用模型。

消息使用客户端 ID、AMP message ID 与 effect request ID 做幂等关联。HTTP/WS payload、SQLite 与附件是
localhost 业务数据，不进入 Kernel 三目录；进入认知边界的事实仍必须使用 AMP 和 Kernel record。

## 约束与非目标

- 当前仅监听本机，不定义局域网、公网、TLS、反向代理或静态前端托管。
- Vue 前端继续由独立 AuroraChat 仓库管理，开发时经 Vite proxy 连接 Dashboard。
- 当前不提供群聊、Bot 附件理解、跨 Episode 记忆或外部数据导入。

## 验收标准

1. 两个用户可经 HTTP/WS 注册、登录、私聊、查询历史并恢复增量消息。
2. 文本发给 Bot 后形成 AMP、独立 episode、回复效果、持久化消息和 WS 推送的可审计闭环。
3. 重放客户端消息或效果请求不重复入库、调用模型或推送回复。
4. `bot.py` 默认共享单 Runtime 启动 Dashboard，`--headless` 不启动 HTTP，退出时完整关闭资源。
5. Dashboard 路由不导入或直接调用 Kernel；localhost 聊天用例不依赖 FastAPI。

## 当前接口

调试路由与应用工厂仅由 `src.dashboard` 承载，`localhost` 不提供反向兼容导出。Dashboard 前端由独立工程
管理，本仓库只维护后端路由/API 适配与 localhost 聊天业务用例。
