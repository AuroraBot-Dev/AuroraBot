# 操作指南

核对日期：2026-11-09。首次使用先运行[安装配置助手](../examples/START.md)。本文保留日常操作边界，不要求新用户一次启用全部能力。

## 连接安装助手

助手默认端口为 10271、实例为 onboarding、数据为 build/onboarding。单次消息用 `--text`；省略时启动持续后端，等待 TUI 或 Panel 提交输入。后端就绪不自动激活模型。

```powershell
uv run --locked python examples/onboarding/main.py
```

另一个终端运行：

```powershell
pnpm --filter @aurorabot/tui start --connect http://127.0.0.1:10271 --instance onboarding
```

需要 Panel 时，先在根目录 `.env` 配置至少 32 位 URL 安全字符的 `AURORA_API_TOKEN`；可以用 `uv run --locked python -c "import secrets; print(secrets.token_urlsafe(32))"` 本机生成。再启动：

```powershell
uv run --locked python examples/onboarding/main.py --token-env AURORA_API_TOKEN --allowed-origin http://127.0.0.1:5173
```

另一个终端运行 `uv run --locked aurora panel`，在页面连接设置填入 `http://127.0.0.1:10271` 与令牌；或在 `.env` 设置 `AURORA_API_URL=http://127.0.0.1:10271` 后重启 Panel 开发服务器，使用自动连接。访问地址使用已允许的 Origin。

助手不开放 TOML 编辑端点；由 terminal 工具协助用户配置。助手自己的模型或 MCP 配置变更后也须重启。

## 启动正式 Bot

助手完成目标目录的配置后，在独立终端启动正式后端：

```powershell
uv run --locked aurora bot
```

此快捷入口调用 scripts/bot.py，默认加载根目录 `.env` 和 `data`，监听 127.0.0.1:10270，要求 AURORA_API_TOKEN。它显式启用完整产品插件，包括 MCP、world、cadence 和 API；实际外部服务和来源由配置选择。

它与最小助手不同：插件集和产品装配由脚本选择，并合并 host.toml 的额外插件。需要完全遵循 host.toml 的插件与装配时，使用通用 CLI 的 `--root`、`--data-dir` 和运行命令，参见 `aurora --help`、`aurora serve --help`。

`--data-dir`、`--env-file`、`--port` 可覆盖路径和端口；`--allowed-origin`、`--allowed-host` 可重复，替换默认白名单。进程已有环境变量优先于环境文件。不要让多个后端共用数据目录。

正式产品默认允许 http://127.0.0.1:5173 和 http://localhost:5173，状态默认只读，交流走产品端点。要开放声明 TOML 编辑，加 `--edit-config`。Ctrl+C 停止接收、等待运行清理并最终落盘。

## TUI

工作区先执行 `pnpm install --frozen-lockfile`。正式产品可用 `uv run --locked aurora tui` 或 `pnpm tui`，读取根目录环境中的令牌；最小无认证助手使用上面的直接 TUI 命令。

| 操作 | 快捷键 |
| --- | --- |
| 交流 / 状态页 | Tab、F1、F2 |
| 发送 / 换行 | Enter / Shift+Enter 或 Alt+Enter |
| 展开工具 | Ctrl+T |
| 取消当前运行 | Ctrl+X |
| 翻阅 / 回到底部 | PgUp、PgDn / F3 |
| 核对 / 明确重试未确认消息 | F5 / F4 |
| 帮助 | F12；输入为空时也可按 ? |
| 退出 TUI | Ctrl+C，后端仍继续运行 |

状态页按 ID / location 筛选；F6 编辑已有地址，Ctrl+N 新建。编辑器 F5 读取、F8 准备保存、Ctrl+D 准备删除、F9 确认、Esc 返回。默认只读开放的地址不能写入。

F7 打开声明 TOML 配置。服务端只允许已登记 ConfigSpec 的文件，不能编辑 host.toml、.env 或任意路径。单文件上限 256 KiB，保存检查全部声明文件的读取修订；冲突后先重读。保存后重启后端生效，不改变当前运行。

`--save-preferences` 显式保存连接选择并退出；正常退出保存页面和全局工具展开偏好。草稿、消息、凭证与请求身份不保存。Windows 默认偏好在 `%APPDATA%/AuroraBot/tui.json`，其他平台在 XDG 配置目录下；`--preferences` 可选择独立文件。

## Panel

`uv run --locked aurora panel` 或 `pnpm panel` 启动本机开发服务器。默认地址为 http://127.0.0.1:5173，前端不会自动启动后端。

开发服务器可读取根目录环境文件中的 AURORA_API_TOKEN 和可选 AURORA_API_URL，通过本机同源接口提供运行期连接默认值；生产构建和 preview 保持手动连接。令牌不写浏览器存储或静态构建。

Panel 提供实例选择、交流与只读状态。Enter 发送、Shift+Enter 换行，输入法选词不会误发送。可发送图片、PDF 和 UTF-8 文本文件，每条最多 8 个、合计 10 MiB；实际模型能力决定能否处理。附件草稿只在页面内存，发送后内容进入后端历史和快照。模型思考独立折叠展示。

## 运行与编辑语义

接纳回执不等于业务完成。运行中追加输入交给现有所有者，关闭客户端不取消 Bot；停止操作必须指定目标运行并等待收尾。

网络结果不确定时先查询，明确重试保留原 session_id、instance_id、request_id 和内容；宿主重启后旧会话过期，不自动重发。ctx 编辑按完整 ID 和 location 整项替换，无跨客户端事务；TOML 编辑有文件修订检查，两者不可混用。

## 常见问题

| 现象 | 先检查 |
| --- | --- |
| 助手未初始化 | 执行带相同 --data-dir 的 --init |
| 模型启动失败 | profile、binding、credential 变量名和供应商参数；不要回显密钥 |
| terminal MCP 启动失败 | uvx 是否在 PATH、首次下载网络、配置命令与启动超时 |
| TUI 无法连接 | 后端是否仍运行、10270 / 10271 是否选对、实例与令牌 |
| 浏览器 401 / 403 | 令牌、Origin、Host 与后端白名单 |
| 配置保存后没变化 | 是否修改了正确数据目录，是否正常重启后端 |
| 上下文过大 | 工具正文、工具定义、历史与输入字符预算，见上下文指南 |
| 恢复失败或动作未知 | 保留原数据核对旧 ID / 插件与工具证据，不自动重试副作用 |

API 结构契约见 [conversation_contract.py](../packages/aurora_bot/src/aurora_bot/conversation_contract.py) 和 [editor_contract.py](../packages/aurora_config/src/aurora_config/editor_contract.py)；开发检查见[开发指南](development.md)。
