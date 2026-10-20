# AuroraBot 落地页

Vue 3 + TypeScript + Vite 应用，默认中文，提供英文和日文切换。

```text
src/assets/   页面使用的 Logo、图标与字体，由 Vite 处理资源引用
src/locales/  中文、英文与日文文案
src/styles/   全局样式与字体声明
```

页面与 favicon 共用 `src/assets/logo.svg`。需要固定 URL、原样复制的文件时再使用 `public/`。

在主仓根目录安装依赖并运行：

```bash
pnpm install --frozen-lockfile
pnpm dev:landing      # http://localhost:5174
pnpm build:landing    # apps/landing/dist
pnpm preview:landing
```

主题与语言选择保存在浏览器本地，语言也可通过 `?lang=en-US`、`?lang=ja-JP` 指定。部署到子路径时可用 `pnpm build:landing --base=/aurora/` 构建。
