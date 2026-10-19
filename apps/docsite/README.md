# AuroraBot 文档站

VitePress 2 应用。`src/` 保存站点正文与 RFC，`public/` 保存静态资源，`.vitepress/config.ts` 与 `.vitepress/theme/` 定义站点和主题，`dist/` 是构建产物。

在仓库根目录运行 `pnpm dev:docs`、`pnpm build:docs`、`pnpm preview:docs`。依赖、检查配置与锁文件由仓库根目录统一管理。

`tsconfig.json` 检查主题代码，`tsconfig.node.json` 检查 VitePress 配置；`pnpm typecheck` 同时执行两者。
