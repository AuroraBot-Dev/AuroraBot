# AuroraBot 落地页

Vue 3 + TypeScript + Vite 应用。文案、图标、字体位于 `src/assets/`，默认中文，提供英文和日文切换。

在主仓根目录安装依赖并运行：

```bash
pnpm install --frozen-lockfile
pnpm dev:landing      # http://localhost:5174
pnpm build:landing    # apps/landing/dist
pnpm preview:landing
```

主题与语言选择保存在浏览器本地，语言也可通过 `?lang=en-US`、`?lang=ja-JP` 指定。部署到子路径时可用 `pnpm build:landing --base=/aurora/` 构建。
