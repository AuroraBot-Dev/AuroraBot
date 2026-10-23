---
order: 2
---

# 离线文档

文档站位于主仓的 `apps/docsite/`，由根目录 pnpm workspace 管理。
安装依赖需要访问包仓库；依赖准备完成后，可以在本机开发、构建和预览文档。

## 准备环境

- Node.js 24，最低 24.12.0；推荐使用根目录 `.node-version` 指定的版本。
- pnpm 12，使用根目录 `package.json` 的 `packageManager` 指定版本。

在仓库根目录安装依赖：

```bash
pnpm install --frozen-lockfile
```

`aurora setup` 也会在找到 pnpm 时安装工作区依赖。

## 开发与构建

在仓库根目录运行：

```bash
pnpm dev docsite                 # 开发服务，http://localhost:5173
pnpm build docsite               # 生产构建，输出 apps/docsite/dist
pnpm preview docsite             # 预览生产构建，地址以终端输出为准
```

也可以通过 CLI 转发文档站命令：

```bash
aurora docs dev
aurora docs build
aurora docs preview
```

在 `apps/docsite/` 内可使用 `pnpm dev`、`pnpm build`、`pnpm preview`。
文档站使用本地搜索，生产构建包含站内搜索索引。外部链接仍需要网络访问。

## 检查与清理

根目录 `pnpm check apps` 会检查前端类型、代码规范、测试，并构建两个应用。
构建会检查文档内部链接；部署工作流也执行同一检查入口，通过后才上传和发布产物。

```bash
pnpm clean artifacts             # 清理工作区构建产物、Vite/VitePress 和检查器缓存，保留依赖
pnpm clean deps                  # 额外删除根目录和各包的 node_modules，保留锁文件
pnpm install --frozen-lockfile   # 删除依赖后重新安装
```

在 `apps/docsite/` 内运行 `pnpm clean`，只清理本站构建产物及 Vite/VitePress 缓存。
缓存位于 `apps/docsite/node_modules/.vitepress`，构建产物位于 `apps/docsite/dist`。
