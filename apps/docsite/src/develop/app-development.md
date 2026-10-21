---
order: 2
---

# 开发应用

前端工作区包含落地页 `apps/landing` 和文档站 `apps/docsite`。需要 Node.js 24 与 pnpm 12，具体版本见根目录 `.node-version` 和 `package.json`。

## 准备与运行

在仓库根目录执行：

```bash
pnpm install --frozen-lockfile
pnpm dev landing                # 落地页，默认端口 5174
pnpm dev docsite                # 文档站，默认端口 5173
```

运行 `pnpm task` 可通过菜单选择任务和目标，也可用 `pnpm dev` 直接选择应用。非交互环境需要明确指定目标。

## 常用任务

```bash
pnpm build all                  # 构建两个应用
pnpm build docsite              # 只构建文档站
pnpm preview docsite            # 预览文档站构建产物
pnpm check apps                 # 前端检查、测试与构建
pnpm dev landing -- --port 5180 # 为单项任务传递参数
pnpm build all --dry-run        # 查看将执行的命令
pnpm build --help               # 查看可用目标
```

构建产物位于各应用的 `dist/`。组合任务中任一命令失败后即停止；需要自动修复格式与规范问题时，运行 `pnpm format all` 并复核差异。

## 清理

`pnpm clean artifacts` 删除构建产物与缓存，保留依赖和源码。`pnpm clean deps` 还会删除 `node_modules`，之后需重新安装依赖。

文档页面的编辑规范见[贡献与修订文档](./docs-contribution)，本地查看方式见[离线文档](../start/offline-docsite)。
