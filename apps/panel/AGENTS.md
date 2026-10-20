# AGENTS.md

## 项目概况

- AuroraBot 面板：Vue 3 + Vite + Naive UI，基于 Vben Admin 5.7 的 pnpm monorepo（turbo 缓存）。中文代码注释与提交信息（conventional commits，czg/commitlint），不要翻译。
- 唯一真实应用是 `apps/panel`（`@aurorabot/panel`）。共享库位于仓库根 `packages/`，工程工具位于 `tooling/`；日常页面改动集中在本目录 `src/`。
- 不要用 OpenCode/其他 AI 生成内容替换 `../../packages/@core` 等底座代码；改动底座后需在根目录运行 `pnpm typecheck` 验证，而 `pnpm typecheck` 检查本应用及其 Node.js 配置。

## 常用命令

- 安装：在主仓根目录运行 `pnpm install --frozen-lockfile`，统一使用 pnpm 12 与根 workspace/catalog/锁文件。
- `pnpm dev`：需先运行 AuroraBot 并在 Console 执行 `/serve`（`http://127.0.0.1:8765`），Vite 代理 `/api` 与 `/healthz`（见 `vite.config.ts`）。登录使用后端 `data/ops/Token.txt` 中的 bootstrap token。
- 校验顺序与 CI（根目录 `.github/workflows/apps.yml`）一致：`pnpm lint` → `pnpm typecheck` → `pnpm test` → `pnpm build`。
- 根目录 `pnpm lint` 统一运行 Prettier、Oxlint、ESLint 和 Stylelint，根目录 `pnpm format` 执行自动修复。
- 单个测试：`pnpm exec vitest run src/api/operation-coverage.test.ts --dom`（根目录 `pnpm test` 使用 `vitest.config.ts`，happy-dom）。
- `tsconfig.json` 检查页面与组件，`tsconfig.node.json` 检查 Vite 配置。

## API 契约（关键）

- 后端是动态 `/api/ops/{path}` catch-all 路由，OpenAPI 无法表达具体 DTO → 前端不做生成类型，`src/api/types/` 按后端契约手工同步。
- 业务 URL 只能出现在 `src/api/modules/`；`client.ts` 负责基址、Bearer 会话与 Operation envelope。
- `operation-coverage.ts` 维护 22 个 GET-only 后端 OperationSpec 与页面路由的映射。后端操作增删时必须同步 `modules/`、`types/`、coverage 映射与测试。
- 面板没有附件、WebSocket 或写操作；世界事件通过 `GET /world/stream` 轮询。

## 页面边界

- Engine 配置、模型、配置、提示词、记忆、日志、诊断、插件和应用页面使用真实后端数据；当前不提供可发送聊天的页面。
- `/chat`（`src/views/aurora/chat.vue`）保留聊天版式，但只读：数据来自 `GET /world/stream` 与 `GET /console` 的世界线回放，不调用写接口、不启动 AgentTree。
- Emoji、表情、屏蔽词、学习、插件市场是 `src/views/aurora/feature-placeholder.vue` 的明确占位，禁止提供 mock 数据或虚构 API。

## 部署

- 纯静态 SPA，`dist` 即全部产物；API 地址是运行时配置（产物中的 `_app-config-*.js`，由 `../../tooling/vite-config/src/plugins/extra-app-config.ts` 生成），改配置无需重新构建。
- 后端只监听 loopback，nginx 反代与容器化部署见 `scripts/deploy/` 及 README「发布与部署」。
