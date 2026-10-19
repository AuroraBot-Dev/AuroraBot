# AuroraBot API boundary

- `client.ts`：API 基址、Bearer 会话、统一 `PanelApiError` 与包含 `control` 的 Operation envelope；成功响应允许 `data=null`。
- `modules/`：按 AuroraBot 后端操作域组织的请求函数；业务 URL 只能出现在这里。
- `types/`：依据 AuroraBot 当前公共契约手工同步的传输 DTO。
- `operation-coverage.ts`：22 个 GET-only OperationSpec 与真实 Vue route 的覆盖映射。

AuroraBot 使用动态 `/api/ops/{path}` 分发，生成的 OpenAPI 只能描述 catch-all 路由，不能表达具体操作 DTO。因此前端不保留空的生成类型；后端契约变化时应同步更新对应领域模块、DTO 和覆盖测试。

面板没有附件、WebSocket 或写操作。世界事件通过 `GET /world/stream` 轮询。
