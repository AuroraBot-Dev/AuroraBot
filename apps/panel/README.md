# 主仓工作区

本应用位于 `apps/panel/`。使用仓库根目录的 Node.js 24、pnpm 12、workspace、catalog 和锁文件；先在主仓执行 `pnpm install --frozen-lockfile`，再用 `pnpm dev:panel`、`pnpm build:panel`。

# AuroraBot Panel

<b>中文</b> | <a href="README.en.md">English</a> | <a href="README.ja.md">日本語</a>

AuroraBot 的只读 Web 观察面板，基于 Vue、Vite、Naive UI 和 Vben Admin。面板连接 AuroraBot 的 ops 后端，用于查看已装配能力、配置、世界线与运行状态。

## 前置

- [Node.js](https://nodejs.org/) 22.18+ 或 24.12+
- [pnpm](https://pnpm.io/) 11+
- 已启动并执行过 `/serve` 的 AuroraBot Console

```bash
npm install -g pnpm   # 如果尚未安装
```

## 本地开发

先在 AuroraBot 主仓启动 Console（aurora 已由主仓 setup 脚本链接；未链接时用 `uv run aurora start`），再在 Console 中执行 `/serve`：

```bash
aurora start
# 在启动后的 Console 中输入 /serve
```

`/serve` 启动的后端默认监听 `http://127.0.0.1:8765`。随后在另一个终端中，从主仓根目录用 `aurora panel` 驱动面板：

```bash
aurora panel dev      # 启动开发服务器
aurora panel build    # 生产构建
```

开发服务器通过 Vite 将 `/api` 与 `/healthz` 转发到后端；登录使用后端生成在 `data/ops/Token.txt` 中的 bootstrap token。跨域部署可通过 `VITE_GLOB_API_URL` 设置 API 地址。

也可以在主仓根目录直接运行：

```bash
pnpm install --frozen-lockfile
pnpm dev:panel
```

## 发布与部署

面板是纯静态 SPA，`dist` 即全部产物；API 地址是运行时配置，部署时直接修改即可，无需重新构建。后端只监听 loopback，面板需与其同机部署：

1. **nginx 反代**：使用 `scripts/deploy/nginx.conf`（托管静态文件并反代 `/api` 与 `/healthz`），并把访问来源加入后端 `config/runtime.toml` 的 `runtime.panel.allowed_origins`。
2. **容器**：用 `scripts/deploy/build-local-docker-image.sh` 构建镜像，以 `--network host` 运行。

纯本地使用也可以直接 `pnpm dev`（Vite 代理）或 `pnpm build && pnpm preview`。远程访问请按主仓文档建立可信隧道，保持后端只监听本机。
