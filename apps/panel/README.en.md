# AuroraBot Panel

<a href="README.md">中文</a> | <b>English</b> | <a href="README.ja.md">日本語</a>

AuroraBot's read-only web observation panel, built with Vue, Vite, Naive UI, and Vben Admin. It connects to the AuroraBot ops backend to inspect assembled capabilities, configuration, the world timeline, and runtime status.

## Requirements

- [Node.js](https://nodejs.org/) 22.18+ or 24.12+
- [pnpm](https://pnpm.io/) 11+
- A running AuroraBot Console with `/serve` enabled

```bash
npm install -g pnpm   # if not yet installed
```

## Local development

Start the Console from the AuroraBot main repository (aurora is linked by the main repo's setup script; otherwise use `uv run aurora start`), then run `/serve` in the Console:

```bash
aurora start
# Enter /serve in the running Console
```

The backend started by `/serve` listens on `http://127.0.0.1:8765` by default. Then, in another terminal, drive the panel with `aurora panel` from the main repository root (`aurora setup` installs workspace dependencies):

```bash
aurora panel dev      # start the dev server
aurora panel build    # production build
```

The dev server proxies `/api` and `/healthz` to the backend through Vite. Log in with the bootstrap token the backend writes to `data/ops/Token.txt`. For cross-origin deployments, set the API address with `VITE_GLOB_API_URL`.

You can also run directly in this repository:

```bash
pnpm install --frozen-lockfile
pnpm dev
```

## Release & deployment

The panel is a pure static SPA; `dist` is the entire artifact, and the API address is a runtime configuration you can change at deploy time without rebuilding. The backend only listens on loopback, so the panel must run on the same machine:

1. **nginx reverse proxy**: use `scripts/deploy/nginx.conf` (serves the static files and proxies `/api` and `/healthz`), and add the access origin to `runtime.panel.allowed_origins` in the backend `config/runtime.toml`.
2. **Container**: build the image with `scripts/deploy/build-local-docker-image.sh` and run it with `--network host`.

For purely local use, `pnpm dev` (Vite proxy) or `pnpm build && pnpm preview` also work. For remote access, follow the main repository's documentation to set up a trusted tunnel while keeping the backend on loopback.
