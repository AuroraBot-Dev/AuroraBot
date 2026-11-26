# 启动示例

> 历史归档：2026-11-09。保留当时的设计、计划与验收语境，不作为当前功能承诺或操作指南；当前入口见 [文档索引](../../INDEX.md)。

在仓库根目录执行，使用 Python 3.12+ 和 uv：

```powershell
uv sync --locked --all-packages
```

使用 TS 客户端或运行完整检查时，先安装前端工作区。pnpm 12.15.0 会按 `package.json` 的声明准备 Node 26.13.0，系统全局 Node 不受影响：

```powershell
pnpm install --frozen-lockfile
pnpm exec node --version
pnpm exec uv run --locked aurora check
# 完整测试包含插件包内测试、原生终端和长耗时集成测试
pnpm exec uv run --locked aurora check --full
```

项目支持的 Node 范围为 `>=26.4.0 <27`，`.node-version` 也固定为 26.13.0。终端里的裸 `node` 仍可能指向系统版本；通过 `pnpm exec` 或 pnpm 脚本使用项目运行时。OpenTUI 原生渲染需要 `--experimental-ffi`，TUI 启动脚本已包含该参数。

`aurora check` 默认执行全部静态检查与快速边界测试；`--test` 只运行快速边界测试，`--test --full` 只运行完整测试，`--coverage` 使用完整测试范围。

以下五个示例使用本地数据和假模型，无需模型密钥、外部模型服务或前端。每个示例使用独立数据目录。

| 示例 | 入口 | 主要依赖与职责 |
| --- | --- | --- |
| 持久化计数器 | [core_counter/main.py](../../../tests/fixtures/runtime_apps/core_counter/main.py) | core：声明、ctx、生命周期与落盘 |
| 控制流 | [control_flow/main.py](../../../tests/fixtures/runtime_apps/control_flow/main.py) | control + core：顺序、分支、循环与并发 |
| 独立 Agent | [react_agent/main.py](../../../tests/fixtures/runtime_apps/react_agent/main.py) | agent + control + adapter.model + core：运行调度、模型工具往返与引导 |
| 默认 Bot | [default_bot/main.py](../../../tests/fixtures/runtime_apps/default_bot/main.py) | bot：TOML 配置、资源工厂和默认装配 |
| 持续巡检宿主 | [live_workshop/main.py](../../../tests/fixtures/runtime_apps/live_workshop/main.py) | bot + CLI/API：持续运行、世界变化、远程观察和报告 |

## 持久化计数器

```powershell
uv run --locked python examples/core_counter/main.py --data-dir build/counter-demo --name visits --amount 2
uv run --locked python examples/core_counter/main.py --data-dir build/counter-demo --name visits --amount 3
```

在新数据目录中，两次输出分别为 `visits: 2` 和 `visits: 5`。同名计数器累加，不同名称独立保存。此示例只依赖 core，业务参数和结果使用普通函数参数及返回值。

## 控制流

```powershell
uv run --locked python examples/control_flow/main.py --data-dir build/control-demo --steps 3 --delay 0.2
```

装配为 `Serial → While(Serial → Branch) → Parallel → 汇总`。默认结果为 `{"count":3,"double":6,"square":9}`。运行时展示控制状态和业务状态；退出只保留最近一次运行的结果，不续跑历史调用。

执行契约和四种组合从 `aurora_control` 导入。控制定义使用 `org.aurora.control:*`，在途状态为 `org.aurora.control:state/control`。此示例不需要 agent、bot 或模型适配包。

使用较大的 `--delay`，在运行中按 Ctrl+C，可观察取消传播及控制状态清理。

## 独立 Agent

```powershell
uv run --locked python examples/react_agent/main.py --data-dir build/agent-demo --guide "保留当前计算进度"
uv run --locked python examples/react_agent/main.py --data-dir build/agent-demo --text "无需行动"
```

第一次由假模型请求本地加法工具，回填观察后输出 `计算结果：5`；流式推理期间通过 `AgentRuntime.submit()` 追加引导。第二次恢复上下文和消费进度，完成一次无需工具的激活。

示例直接装配 `ReActAgent`、`ModelCall`、`ToolExecutor`、`ReActDefaults` 和 `AgentRuntime`，不导入 bot。宿主提供状态地址及执行入口，并管理资源关闭与结果保留。运行回执通过 `wait()` 等待，等待者取消与 agent 取消分别管理；宿主关闭时停止提交并等待 runtime 收尾，再关闭模型。

其他可观察场景：

```powershell
# 普通工具失败进入下一轮模型观察
uv run --locked python examples/react_agent/main.py --data-dir build/agent-failure --tool-error
# 工具超时
uv run --locked python examples/react_agent/main.py --data-dir build/agent-timeout --tool-delay 0.2 --timeout 0.01
# 执行工具期间可按 Ctrl+C，随后用同一目录恢复
uv run --locked python examples/react_agent/main.py --data-dir build/agent-cancel --tool-delay 10 --timeout 20
uv run --locked python examples/react_agent/main.py --data-dir build/agent-cancel --text "无需行动"
```

中断的工具轮次保留可获得的结果，下一次激活接纳观察，不自动重复执行动作。模型文本是内部输出，不自动发送用户消息。

## 默认 Bot

```powershell
uv run --locked python examples/default_bot/main.py --data-dir build/bot-demo
uv run --locked python examples/default_bot/main.py --data-dir build/bot-demo --text "你好"
uv run --locked python examples/default_bot/main.py --data-dir build/bot-demo --profile secondary --text "再次见面"
```

无输入时只启动装配，不自动激活。提交文本后，假模型调用回显工具。`--profile` 保存模型角色绑定，后续启动继续使用该选择。配置由包内 `config.tomls/` 模板生成，位于 `<data-dir>/config/`，模型 profile、角色绑定和 bot 配置分开保存；业务状态保存在 ctx 快照中。示例的 bot 配置文件为 `org.aurora.bot/bot.toml`。

bot 提供 `org.aurora.bot:assemblies/default`、运行操作和 CLI 命令。它分配的消息、引导和运行状态地址归属 bot；注入这些地址的 agent 组件定义归属 `org.aurora.agent`。

持续运行离线默认 bot，并显式开放直接交流端点及 bot 状态：

```powershell
uv run --locked python examples/default_bot/main.py --data-dir build/bot-api --serve --port 10270
```

另开一个交互终端，在仓库根目录启动 TUI：

```powershell
pnpm --filter @aurorabot/tui start --connect http://127.0.0.1:10270 --instance main
```

顶部“交流 / 状态”页签可点击，或使用 Tab、F1、F2 切换。交流页按运行分组，模型文本显示为过程输出；Enter 发送，Shift+Enter 或 Alt+Enter 换行，也支持粘贴多行文本。运行中发送消息会追加引导。Ctrl+T 展开工具参数与结果，Ctrl+X 取消当前运行，点击运行内“停止”可指定目标。状态页展示后端开放的 ctx，可按 ID 或 location 筛选，↑/↓ 选择地址，F6 编辑选中项，Ctrl+N 填写新地址。

ctx 编辑器使用完整状态 ID、精确 location（JSON 对象）和 JSON 值，Tab 切换字段。F5 重新读取并替换草稿；F8 准备整项替换，Ctrl+D 准备删除；核对目标与内容后按 F9 执行，Esc 取消确认，再按 Esc 关闭编辑器并丢弃未保存草稿。JSON `null` 与地址不存在有不同反馈。写入仍受宿主 `--keys` 限制，不扩大开放范围；ctx 的读改写不是事务，也没有跨客户端冲突保护。写入配置状态仅覆盖运行期 ctx，不保存 TOML，不自动重建模型或工具。

TOML 配置编辑需要宿主显式开放，可在离线示例启动时添加 `--edit-config`：

```powershell
uv run --locked python examples/default_bot/main.py --data-dir build/bot-api --serve --edit-config
```

TUI 中按 F7 打开配置文件列表，↑/↓ 选择，F5 读取；Tab 进入原始 TOML 编辑区，F8 准备保存，F9 确认。保存保留提交文本和注释，经全部声明配置的结构、默认值及关联校验后替换文件，提示“重启后端后生效”；当前 ctx、模型、工具及正在执行的运行保持原配置。校验不创建资源，因此不能替代重启时的资源创建验证。凭证继续使用环境变量引用，不把密钥填写到配置中。

配置端点只访问已登记的 `ConfigSpec` 文件，不编辑 `host.toml`、`.env` 或任意路径。单文件编辑上限为 256 KiB；保存携带覆盖全部声明文件的读取修订，任一文件变化返回冲突并保留草稿，需重新读取后编辑。同一宿主的保存串行执行；不能保证与外部编辑器之间的跨进程原子比较，也不提供跨文件事务。保存失败不会把配置注入 ctx。ctx 与 TOML 写入遇到断线或响应丢失时均不自动重试，应先 F5 读取核对；编辑草稿不进入本地偏好。

底栏 `? 帮助` 可点击。输入为空时按 `?`（Shift+/）展开分组快捷键面板；已有文字时问号正常输入，F12 随时打开帮助。面板打开后按 `?`、Esc 或 F12 关闭，恢复原页面、草稿和焦点；帮助期间不发送消息、不切页或执行运行操作，Ctrl+C 仍可退出。宽终端分栏展示，窄终端纵向排列，可用 ↑/↓、PgUp/PgDn 或鼠标滚动翻阅。

模型输出及历史模型消息默认按 Markdown 渲染，包括标题、列表、强调、代码块和表格；流式输出会增量更新。用户输入和工具参数/结果保持原文展示。

PgUp/PgDn 翻阅，F3 回到底部。向上滚动时新输出不抢占位置；切页保留草稿、滚动位置和工具展开状态。编辑器外，运行结果不确定时 F5 核对，F4 明确重试最近一条未确认交流请求，保持原身份；重启后旧请求不自动重放。Ctrl+C 只退出 TUI，后端继续运行；在后端终端按 Ctrl+C 才关闭宿主。界面保留本次连接观察到的运行活动，断线期间不补发历史事件。

连接设置可以显式保存，下次启动无需重复传参。保存命令立即退出，不要求交互终端，也不连接后端：

```powershell
pnpm --filter @aurorabot/tui start --connect http://127.0.0.1:10270 --instance main --save-preferences
pnpm --filter @aurorabot/tui start
```

启动优先级为命令行参数、本地偏好、内置默认值。普通启动的 `--connect` / `--instance` 只覆盖本次连接；只有 `--save-preferences` 才保存连接选择。切换到不同地址且未指定 `--instance` 时，自动选择新后端提供的首个实例，不沿用旧后端的实例。地址仅接受不含凭证、查询参数和片段的 HTTP(S) URL。

本地偏好默认位于 Windows 的 `%APPDATA%/AuroraBot/tui.json`（无 APPDATA 时使用用户目录下的 `AppData/Roaming`），其他系统使用 `$XDG_CONFIG_HOME/aurorabot/tui.json` 或 `~/.config/aurorabot/tui.json`。`--preferences PATH` 可指定独立文件；相对路径以 TUI 进程工作目录为准，跨目录使用时建议传绝对路径。`--help` 显示当前默认路径。

正常退出时自动保存改变的页面和 Ctrl+T 全局工具展开偏好，下次启动恢复页面与输入焦点。按运行单独展开的工具、筛选词、草稿、消息和请求身份不保存。保存前重新读取文件并合并本次改变的界面字段；多个进程同时写同一文件时，最后一次完整写入生效，需要独立偏好时指定不同文件。

文件使用版本 1 的 JSON，允许字段为 `version`、`connect`、`instance`、`page`（`chat` / `state`）和 `showTools`（布尔值）。删除 `instance` 字段恢复自动选择。缺失文件使用默认值；无效 JSON、未知版本或字段会报告错误并保留原文件，需手动修正或换用其他偏好文件。写入失败会在终端恢复后报告，不影响后端运行。本地偏好不进入后端 TOML、ctx 或业务快照。

也可以使用共享 Node 客户端（在工作区执行）：

```ts
import { CtxClient } from '@aurorabot/client';

const client = new CtxClient('http://127.0.0.1:10270');
try {
  const info = await client.conversation.info();
  const message = {
    session_id: info.session_id,
    instance_id: info.instance_ids[0]!,
    request_id: crypto.randomUUID(),
    text: '你好',
  };
  const receipt = await client.conversation.submit(message);
  console.log('引导已接纳', receipt);
  console.log(await client.conversation.query({
    session_id: message.session_id,
    instance_id: message.instance_id,
    request_id: message.request_id,
  }));
} finally {
  await client.close();
}
```

`accepted` 表示接纳，查询的 `run_status` 才表示关联运行的进度；pending 包括排队和清理。需要停止时调用 `client.conversation.cancel({session_id, instance_id, run_id})`，目标来自同一回执。运行中提交新 request_id 会追加引导，收尾边界会关联下一次运行；关闭客户端不取消 bot。

网络结果不确定时保留原 message，先按其身份查询；同一会话下显式重试须使用原 request_id 和原文本，客户端不会自动重发。宿主重启返回 session_expired，需核对恢复状态后再决定是否发起新消息。每会话最多保留 4096 条回执，达到上限拒绝新消息，旧回执仍可查询；不承诺跨重启去重。完整信封和错误边界见[设计文档](aurorabot-design-v0.2.3.md#102-界面动作边界)。

已配置默认装配的 CLI 宿主可用 `serve --endpoints '["org.aurora.bot:endpoints/conversation"]'` 显式开放该端点；ctx 状态仍由 `--keys` 独立选择。`aurora_api` 插件提供端点接收方声明，未启用时不妨碍进程内运行；安装包不会自动启用插件或开放路由。默认仍限本机客户端，不接受浏览器 Origin；浏览器访问须显式启用下述访问策略。

### 浏览器工作台（Panel）

Panel 使用 Vue、KunUI、Lucide、Pinia 和 Vue Router，提供连接、Bot 实例选择、交流和只读状态页，复用共享 client。页面路由为 `/#/conversation` 和 `/#/state`，可使用浏览器前进/后退，切页不重建订阅连接。先安装工作区依赖：

```powershell
pnpm install --frozen-lockfile
```

已有完整框架配置时，在仓库根目录加载 `.env` 启动后端。文件应包含 `AURORA_API_TOKEN` 以及配置引用的模型和 MCP 凭证变量：

```powershell
uv run --locked aurora bot
```

也可以用离线默认 Bot 验证界面，不需要真实模型密钥：

```powershell
$env:AURORA_API_TOKEN = uv run --locked python -c "import secrets; print(secrets.token_urlsafe(32))"
uv run --locked python examples/default_bot/main.py --data-dir build/panel-demo --serve --port 10270 --token-env AURORA_API_TOKEN --allowed-origin http://127.0.0.1:5173
```

另开终端，在仓库根目录执行 `pnpm panel` 或 `uv run --locked aurora panel`，访问 `http://127.0.0.1:5173`。开发服务器从仓库根目录加载 `.env`，页面使用其中的 `AURORA_API_TOKEN` 自动连接 `http://127.0.0.1:10270`；可用 `AURORA_API_URL` 指定后端地址，已有进程环境变量优先。根目录的 `.env.local` 和对应 Vite 模式文件也遵循 Vite 的加载优先级。修改环境文件后须重启 Panel 开发服务器。未配置令牌或连接失败时，可在连接设置中手动填写地址和令牌；离线示例可使用示例终端生成的令牌。开发服务器固定回环地址与端口，端口占用时明确退出；若自行换端口，须同步后端 Origin 白名单。已有配置的产品宿主也可通过 `scripts/bot.py` 开放相同来源，详情见下节。

自动连接配置仅通过本机同源 POST 接口在运行时提供，不写入浏览器存储、页面状态或静态构建产物。页面启动时尝试一次，手动连接、断开或关闭页面会取消尚未完成的默认配置请求；不会自动启动后端或提交消息。生产构建与 `preview` 保持手动连接。

连接后选择目标 Bot，Enter 发送、Shift+Enter 换行；中文输入法确认候选词不会发送消息。运行中可追加引导，模型过程及工具参数/结果按运行显示；接纳状态与完成回执分开，停止操作指定运行并等待收尾。接纳结果不确定时先核对，只有点击“用原请求重试”才再次提交相同身份；后端重启后旧请求失效，不自动重发。

点击附件按钮可选择 PNG、JPEG、WebP、GIF、PDF，以及 UTF-8 的 TXT、Markdown、CSV、JSON；每条消息最多 8 个、合计 10 MiB，可只发送附件。发送前可移除，切换实例或 API 地址分别保存附件草稿；仅保存在当前页面内存。图片和 PDF 作为原生内容块发送，文本文件解码后连同文件名进入消息；模型实际支持的文件格式由供应商决定。附件随消息进入后端上下文及快照，不依赖原文件路径。重试使用原请求身份和同一份附件，不重新读取本地文件。Panel 将模型返回的思考增量显示在独立的折叠区，回答和工具活动分别展示。

默认将 primary 聊天模型视为多模态模型，`capabilities.file_input` 默认为 true；仅文本部署可显式关闭。思考在 `org.aurora.adapter/model/profiles.toml` 的对应 profile 配置，例如：

```toml
[primary]
adapter = "org.aurora.adapter:adapters/model/litellm"
provider = "deepseek"
model = "deepseek-flash"
credential = "DEEPSEEK_API_KEY"
reasoning_effort = "high"

[primary.thinking]
type = "enabled"

[primary.capabilities]
streaming = true
tool_calls = true
file_input = true
```

未填写 thinking 或 reasoning_effort 时沿用供应商默认，不再强制关闭 DeepSeek 思考。支持开关的服务可用 `type="disabled"`；Anthropic 显式启用时可在 thinking 表内设置 `budget_tokens=4096`。OpenAI 推理模型使用其支持的 reasoning_effort，不添加不支持的 thinking 开关；SDK/供应商拒绝的参数不会自动降级。思考文本、签名及隐藏思考块在完整响应、流式响应和工具往返中保留，签名及隐藏数据不展示为回答。旧文本快照可继续读取，不补造旧思考内容；此更新不新增公共 ID。

程序内通过 `runtime.submit({"kind": "model_input", "content": [...]})` 提交结构化引导；content 使用 `{"type":"text","text":"说明"}`、`{"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}` 或 `{"type":"file","file":{"filename":"报告.pdf","file_data":"data:application/pdf;base64,..."}}`。图片也支持 HTTPS URL，文件可改用 file_id 指定供应商文件 ID 或其支持的 HTTPS URL；不接受宿主本地路径。普通字符串和其他业务 JSON 引导继续保持原语义。

QQ 世界消息经 cadence 原样转发或 `attend_events` 决策转交时，会从完整事件的 OneBot `image` 段提取图片，转换为上述结构化输入；原始引导文本、事件来源、会话、消息 ID 和图片段序号一并保留。决策视图即使截短正文，也按记录 ID 从归档读取图片来源。支持 `data.url` 或 `data.file` 中的 HTTPS URL、图片 data URI；仅有文件名、本地路径或 HTTP URL 时明确提示图片未送入视觉输入，不自动下载或改写地址。每次引导最多附带 15 张图片，内嵌文件合计最多 10 MiB，超限部分明确提示；主模型须支持图片输入。`observe`、`review_work` 不额外提取图片，已消费事件不因升级重放，旧快照不补写图片块。

状态页仅浏览后端已经开放的状态，可按 ID 或 location 筛选，值作为文本显示。切页保留草稿，各实例与 API 地址的草稿分开；这些草稿、令牌和连接设置都不写浏览器存储。刷新后重新连接，通过“已保存的上下文”查看后端历史；本页观察的过程不是持久日志。刷新、断开或关闭页面仅停止观察，不取消后端任务。连接尚未完成时也可点击“断开”。

生产构建与本机预览：

```powershell
pnpm --filter @aurorabot/panel build
pnpm --filter @aurorabot/panel preview
```

产物位于 `apps/aurora_panel/dist`，预览地址为 `http://127.0.0.1:4173`，需相应开放这个 Origin。生产页面默认以当前页面的 Origin 作为 API 地址；可在连接表单中改为其他明确开放的 API Origin。通过同源 HTTPS 代理部署静态资源及 API 时，保持 `/ctx`、`/conversation` 等 API 路径转发与 WS Upgrade，后端继续进行来源及令牌校验。令牌不放入 Vite 构建变量或静态文件。

前端按 `layouts`、`views`、`components`、`composables`、`stores`、`services` 分工，工程结构与依赖边界见[架构设计](aurorabot-design-v0.2.3.md#102-界面动作边界)。开发时运行 `pnpm --filter @aurorabot/panel typecheck` 检查 TypeScript 与严格模板类型，`pnpm exec vitest run apps/aurora_panel` 执行服务和页面回归；图标从 `@lucide/vue` 按需导入，KunUI 品牌 token 统一在 `src/theme/index.css` 配置，强调色 `#4B79EC` 和对比色 `#ECBE4B` 与 TUI 一致。

本切片未提供 ctx/TOML 编辑、浏览器偏好持久化或完整 Markdown 渲染。界面与连接回归见 `apps/aurora_panel/tests`、`tests/e2e/test_panel.py`，浏览器和布局验收记录见 [变更记录](../../CHAGELOG.md)。

### 浏览器访问与运行期认证

后端仍监听 `127.0.0.1`。开发页面可通过明确的 Origin 白名单跨端口访问；生产环境由反向代理提供 HTTPS/WSS，静态页面优先同源部署。启用浏览器来源或额外 Host 时必须同时提供访问令牌；同源也需要显式列入来源白名单。令牌授予宿主已经开放的全部状态和端点，不提供多用户或每个状态的权限隔离。

先在当前终端生成令牌，再启动已配置好的宿主；令牌值不作为命令行参数传递：

```powershell
$env:AURORA_API_TOKEN = uv run --locked python -c "import secrets; print(secrets.token_urlsafe(32))"
uv run --locked aurora bot --data-dir data --token-env AURORA_API_TOKEN --allowed-origin http://localhost:5173
```

`--allowed-origin` 可重复，要求精确的 `协议://主机[:端口]`，不含路径、尾斜杠、通配符或 `null`。`localhost` 和 `127.0.0.1` 是不同来源，端口也参与匹配。`--allowed-host` 可重复，指定小写 ASCII 域名或 IPv4 地址，不含端口；默认只允许 localhost 和 127.0.0.1，显式提供时替换默认列表。这些参数不扩大 `--keys`、`--read-only-keys` 或 `--endpoints` 的开放范围。

通用 CLI 的同等选项为 `serve --token-env NAME --allowed-origins JSON数组 --allowed-hosts JSON数组`。浏览器页通过 `new CtxClient(apiOrigin, { token })` 连接，token 由界面在运行时取得，不写入前端源码、构建变量、URL 或浏览器持久存储。Python 使用 `CtxClient(url, token=token)`。已有 CLI 与 TUI 使用同一环境变量的值：

```powershell
uv run --locked aurora --connect http://127.0.0.1:10270 --connect-token-env AURORA_API_TOKEN ctx list
pnpm --filter @aurorabot/tui start --connect http://127.0.0.1:10270 --token-env AURORA_API_TOKEN
```

HTTP 通过 `Authorization: Bearer <token>` 认证；CORS 预检只允许已开放的路径、方法和 Authorization/Content-Type 请求头，不需要令牌。错误来源或 Host 返回 403，缺失或错误令牌返回 401，允许来源能读取错误信封。共享 client 不发送 HTTP cookie，不自动重试动作请求。

WS 先检查 Origin/Host，再要求在 10 秒内发送首帧 `{ "access_token": "<token>", "key": "<可选状态 ID>", "location": {} }`；认证成功后才创建订阅并返回 ready。无认证的本机模式仍使用原有过滤帧，不发送 access_token。认证失败返回 unauthorized 信封并以 1008 关闭，client 停止重连；网络断线后重新认证、订阅并刷新状态，不重放业务动作。接口定义见生成契约中的 WatchHandshake，过滤条件仍为 WatchRequest。

生产反向代理须终止 TLS、支持 WS Upgrade，并原样转发 Origin、Authorization 和明确允许的 Host。将公开域名加入 `--allowed-host`、页面的 HTTPS 来源加入 `--allowed-origin`，按需保留本机 Host 以供 CLI/TUI 使用；API 不信任 Forwarded/X-Forwarded-* 来改变来源或认证判断。后端不直接监听公网，不支持代理路径前缀。令牌只在进程内使用，要求 32–256 位 URL 安全字符；更换环境变量后重启宿主和客户端才能轮换，已连接 WS 随宿主关闭断开。

来源与浏览器传输规则参考 [CORS](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS) 和 [WebSocket 构造器](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket/WebSocket)。认证与默认装配回归见 `packages/aurora_api/tests/contract/test_browser_access.py`、`tests/e2e/test_browser_conversation.py`；真实浏览器验收记录见 [变更记录](../../CHAGELOG.md)。


## 持续巡检宿主

```powershell
uv run --locked python examples/live_workshop/main.py --data-dir build/workshop-demo serve --port 10270
```

该进程持续运行，模拟来源通过正式 world 归档事件，cadence 将事件交给同一个 AgentRuntime 触发巡检。工具内部组合四种控制组件，报告保存在本地台账中。按 Ctrl+C 关闭宿主、任务、模型和存储。

`aurora_world` 已提供独立的世界记录、来源去重、按位置读取、来源登记、固定身份接纳、可选 TOML 装配与后台主循环托管，W2.3 还提供时间与天气周期来源，接口见[世界输入设计](aurorabot-design-v0.2.3.md#77-直接交流与世界输入)。本示例已使用正式来源工厂、TOML 装配及 cadence；模拟来源仅提交事件，直接交流复用同一 AgentRuntime。仅安装 core/world 的来源装配、接收及恢复验收使用 `tests/fixtures/world_roundtrip.py`，不另增第六条示例路径。

TOML 路径需要安装 `aurora-world[config]`，显式启用 aurora_config、aurora_world、aurora_world.configuration 及来源提供插件；宿主同时装配 `configuration_component`、`records.component(hooks)` 和 `configured_sources_component(ctx, hooks, records, depends_on=("aurora_world/records",))`。后者在 config 阶段读取 `org.aurora.world/config.toml`，默认空列表不启动任何来源。每个 `[[sources]]` 包含 source 定义 ID、唯一 source_id 和可选的 `[sources.config]`。来源参数不承载运行期凭证；修改配置需重新启动，状态覆盖不保存到文件。夹具的 `--configured` 模式验证此路径：

```powershell
uv run --locked python tests/fixtures/world_roundtrip.py .aurora/world-config-check --configured
```

重复运行同一存储目录可验证去重与恢复。后台失败状态位于 `org.aurora.world:state/sources`，按 source_id 查询或订阅；失败关闭对应来源入口，其他来源继续接纳，资源在宿主关闭时释放。配置及运行状态均不进入业务快照。

启用 world 的默认装配会在每次推理前刷新近期事件和环境观察，将其作为临时 user 视图提供给模型。bot 配置文件可添加以下可选段；产品默认文件为 `org.aurora.bot/config.toml`，本示例为 `org.aurora.bot/bot.toml`，修改后重启生效：

```toml
[context_view]
enabled = true
events = true
environment = true
notes = true
actions = true
max_chars = 12000
```

缺少该段时采用上述默认值；`enabled=false` 关闭临时视图，另外四个开关分别控制事件、环境、已启用的工作笔记和行动证据。字符预算包含视图元数据，各类非空材料平分预算并优先呈现最新记录；超长正文标记 abridged，整条省略计入 omitted，已呈现记录保留完整身份。近期事件并非完整归档，环境观察也不属于事件归档；该预算不裁剪消息历史或数据库。离线巡检模型识别并跳过 `kind=business_context` 观察块和 `kind=input_budget` 历史省略提示，只对引导生成巡检动作；真实模型如何使用视图须另行验收。直接交流、工具关联和历史恢复保持原有行为，`--direct-only` 不生成世界视图。

需要约束包含历史消息与工具定义的完整模型请求时，在 bot 配置文件中添加并重启：

```toml
[input_budget]
enabled = true
max_chars = 128000
```

默认关闭，最小预算为 1024。预算覆盖统一 ModelRequest 的文本 JSON 字符数，包含 system、业务观察、工具定义、历史消息、思考及转义；内嵌二进制编码以元数据占位计数，并对请求内文件另设 10 MiB 合计预算；不等同于供应商 token 上限。超限时只省略较早的完整交流段，保留当前交流中的引导和完整工具关系，并提供计入预算的省略提示。持久历史、笔记和归档保留原样，当前业务视图仍使用自己的 context_view 预算。正常空回复也会保存独立结束位置，连续静默观察及重启后仍可裁剪；不会添加空白回复消息。旧快照中未记录的静默结束无法可靠推断，不自动将连续输入拆为已完成交流。

system、观察、工具定义或当前交流本身放不下时，运行返回 ModelInputBudgetExceeded，不继续请求模型。可以调整预算或输入策略后显式再次激活；已经完成的工具不会因预算失败重复执行，原始结果仍留存。运行中的长任务没有完整回复边界时也可能超限。行为及恢复回归见 `tests/e2e/test_input_budget_integration.py`，详细边界见[完整请求字符预算](aurora_bot_ctx_prompt_design.md#已实现的完整请求字符预算)。

工作笔记独立于 world，默认关闭。在同一个 bot 配置文件中添加以下配置并重启，即可向模型提供 notes_write、notes_read 和 notes_list；不需要将它们手工填入 tools：

```toml
[notes]
enabled = true
```

notes_write 创建示例参数：

```json
{
  "note_id": "inspection",
  "expected_revision": 0,
  "text": "等待核实通知结果，尚未确认发送成功。",
  "status": "active",
  "references": []
}
```

更新时携带最近读取到的 revision，并完整提供正文、状态和引用。冲突返回 note_conflict，原文保持不变。active 笔记在下一轮视图中可见且不会随时间过期；status=archived 将其移出当前视图，仍可通过 notes_read 或 notes_list 的 status=all 读取。notes_list 返回 200 字符预览和 next_after，每页最多 50 条；notes_read 返回全文。每实例最多 128 条，单条正文最多 16000 字符，达到容量后仍可更新已有笔记，归档不释放容量。

笔记由宿主快照保存，正常关闭后恢复；关闭 `[notes]` 不删除已有内容，恢复也不自动执行计划。笔记和引用本身不证明工具动作成功。`scripts/bot.py` 将笔记作为只读状态开放，可用 ctx get 读取 `org.aurora.bot:state/notes`、location 为目标 instance_id；`[context_view] notes=false` 只关闭视图展示，工具仍可使用。具体数据边界见[主动上下文设计](aurora_bot_ctx_prompt_design.md#已实现的持久工作笔记)。离线巡检示例不模拟模型自主写笔记，工具往返、取消与恢复由 `tests/e2e/test_work_notes_integration.py` 验证。

需要按视图或笔记中的 world_event 引用读取事件原文时，在同一个 bot 配置文件中启用：

```toml
[archive]
enabled = true
max_chars = 8000
```

该工具要求宿主已经装配 world 记录服务；live_workshop 的持续模式满足此条件，`--direct-only` 不支持此配置。不要将内置工具手工加入 tools 列表。模型调用 world_read_event 的参数为 `{"journal_id":"引用中的数据库 ID","record_id":"引用中的记录 ID","offset":0}`；返回 text 为原始 JSON 片段，按 next_offset 继续，直到 null 表示结束。各页 text 拼接后才构成完整 JSON；字符串载荷也保留 JSON 引号和转义，不能把第一页当作完整事件。

max_chars 限制每页 value 的完整 JSON 长度，含元数据及转义、不含工具结果外层信封，范围 1024–32000；不限制累计消息历史或整次模型输入。错库、缺失记录、越界分别返回 archive_wrong_journal、archive_not_found、archive_invalid_offset；服务不可用或元数据过长也明确失败，不自动换库或重试。工具只读取已知事件引用，不检索环境观察或 tool_call，不消费、重放事件或将事项标为完成。事件过期及重启后的引用读取由 `tests/e2e/test_event_archive_integration.py` 验证。

需要保存并核对工具调用结果时，在同一个 bot 配置中启用并重启：

```toml
[actions]
enabled = true
max_chars = 8000
```

该功能独立于 world 和 notes，不在 tools 中手工声明。模型可以使用 `actions_read`，例如 `{"run_id":"原运行身份","call_id":"原工具调用身份","offset":0}`；按 next_offset 继续分页，至 null 后拼接 text 得到完整证据 JSON。近期视图提供最近 16 次调用的引用及 outcome；`[context_view] actions=false` 只隐藏摘要。

completed/failed 表示工具返回成功/错误，unknown 表示需要核实，not_executed 表示执行器未进入调用；这些状态不由笔记内容决定。结果缺失不证明动作未发生，不自动重试。相同实例内 run_id/call_id 不允许复用；重复引用阻止整个新批次。记录独立保存于 bot 命名空间的 actions.sqlite3，关闭功能不删除记录，完整备份须在停机后包含数据库。当前不自动裁剪记录。回归见 `tests/e2e/test_action_evidence_integration.py`，存储、预算和错误边界见[行动证据设计](aurora_bot_ctx_prompt_design.md#已实现的行动证据)。

在另一个终端观察报告及控制状态：

```powershell
uv run --locked aurora --connect http://127.0.0.1:10270 ctx watch --key dev.example.workshop:state/reports
uv run --locked aurora --connect http://127.0.0.1:10270 ctx watch --key org.aurora.control:state/control
```

手动交流可通过 TUI 连接本机地址并选择 `workshop`，也可通过正式 conversation 端点提交：

```powershell
$base = "http://127.0.0.1:10270"
$info = Invoke-RestMethod "$base/conversation/info" -Method Post -ContentType "application/json" -Body '{}'
$body = @{ session_id = $info.result.session_id; instance_id = "workshop"; request_id = [guid]::NewGuid().ToString(); text = "手动巡检" } | ConvertTo-Json
Invoke-RestMethod "$base/conversation/submit" -Method Post -ContentType "application/json" -Body ([Text.Encoding]::UTF8.GetBytes($body))
```

离线模型接受普通文本；也可将 `text` 填为含 `text`、`steps`、`delay`、`fail` 的 JSON 文本以演示步骤和工具失败。运行中交流仍属于当前运行；取消使用 conversation/cancel 的 session_id、instance_id、run_id，取消后需显式提交后续工作。设置 `settings.automatic=false` 暂停产生新巡检事件，已归档事件仍由 cadence 接纳，环境 tick 继续变化。

仅验证直接交流时使用独立目录：

```powershell
uv run --locked python examples/live_workshop/main.py --direct-only --data-dir build/workshop-direct serve --port 10270
```

该模式不启用 world/configuration/cadence 插件，不生成世界事件数据库。普通模式的来源与消费配置分别位于 `config/org.aurora.world/world.toml`、`config/org.aurora.bot/cadence.toml`；模板只补缺失文件。API 仅允许修改示例 settings 与模型 bindings，其他状态只读；绑定的文件配置仍需通过 TOML 修改并重启。

旧示例的 `dev.example.workshop:state/request` 及自有调度处理器已移除，不提供兼容转发。旧快照若包含这些状态须保留原目录并换新数据目录运行；本次不自动改写用户快照。已有 world/cadence 快照也不能直接以 --direct-only 恢复。报告台账仍持久保存，成功运行保留最近一组引导及完整工具往返，未收束工具结果沿默认恢复语义保留；恢复不重试工具副作用。

## 插件发现与定义目录

插件发现分组为 `aurora.plugins`，依赖插件必须显式列出；CLI 内置启用 aurora_config 并装配配置服务，程序化宿主需显式启用和装配。定义查询不创建模型客户端：

```powershell
uv run --locked aurora --plugin aurora_control --plugin aurora_agent.model --plugin aurora_adapter.model id list
```

默认 bot 的宿主插件清单为：

```toml
plugins = [
  "aurora_config",
  "aurora_adapter.model",
  "aurora_agent.model",
  "aurora_agent.react",
  "aurora_agent.tools",
  "aurora_agent.react_defaults",
  "aurora_bot.assembly",
]
assembly = "org.aurora.bot:assemblies/default"
```

只使用执行契约不要求启用控制插件；使用四种控制组合时额外启用 `aurora_control`。组件定义、执行端口和状态归属见[公共 ID 目录](aurorabot-id-catalog-v0.2.3.md)。

## 使用已有配置启动真实模型后端

模型与 MCP 统一安装包为 `aurora-adapter`，模块分别为 `aurora_adapter.model` 和 `aurora_adapter.mcp`。独立模型配置插件安装 `[model]`，LiteLLM 安装 `[litellm]`；默认 bot 已依赖后者。模型配置位于 `<data-dir>/config/org.aurora.adapter/model/profiles.toml` 与 `model/bindings.toml`，MCP 配置位于同一命名空间下的 `mcp.toml`。旧包、插件名、配置路径和公共 ID 的迁移见[变更记录](../../CHAGELOG.md#2026-11-04)，宿主不自动迁移旧数据。

三种快捷启动统一由 `scripts/` 中的脚本维护，`aurora` 与根目录 pnpm 命令调用同一份脚本，无须填写启动参数：

| 程序 | Aurora 命令 | pnpm 命令 | 唯一快捷脚本 |
| --- | --- | --- | --- |
| Bot 后端 | `aurora bot` | `pnpm bot` | `scripts/bot.py` |
| Panel 网页 | `aurora panel` | `pnpm panel` | `scripts/panel.py` |
| TUI 终端 | `aurora tui` | `pnpm tui` | `scripts/tui.py` |

在仓库根目录分别开终端运行后端和所需界面。未激活 Python 虚拟环境时，使用 `uv run --locked aurora bot` 等命令；从其他目录调用 CLI 时用 `aurora --root 项目绝对路径 tui` 指定工作区。这些是源码工作区快捷命令，需要已安装 Python 工作区依赖，前端还需 `pnpm install`；独立安装 CLI 后须提供含脚本的工作区。Panel 不自动启动后端或填充浏览器令牌。

参数原样交给脚本，例如 `aurora bot --edit-config` 与 `pnpm bot --edit-config` 等价，`--help` 显示对应程序帮助。完整产品入口已从根目录迁至 `scripts/bot.py`，不保留旧入口；也可直接执行 `uv run --locked python scripts/bot.py`。现有 `.env`、`data` 与 TOML 配置路径不变。

Bot 复用现有 CLI 宿主、配置服务和 MCP 产品装配：

```powershell
uv sync --locked --all-packages
uv run --locked aurora bot
```

入口显式启用模型、ReAct、工具、控制组件、MCP 客户端及工具/世界桥、world 配置、环境来源、cadence 和 API，选择 `org.aurora.adapter:assemblies/mcp/default_bot`。`host.toml` 中的额外插件继续加载并校验；该入口的产品装配选择优先于文件中的 `assembly`，不改写原文件。需要完全由 `host.toml` 选择装配与插件时使用 `aurora` CLI。

默认读取项目根目录的 `.env` 和 `data/`，不受当前终端目录影响；显式传入的相对路径按当前终端目录解析。进程中已有的环境变量优先于 `.env`，可用 `--env-file` 指定其他文件。访问令牌默认读取 `AURORA_API_TOKEN`（32 至 256 位 URL 安全字符）；凭证仅供运行期解析，不写入配置、状态或日志。未设置令牌或访问策略无效时，在创建模型与外部连接之前退出。

API 默认监听 `127.0.0.1:10270`，允许 `http://127.0.0.1:5173` 与 `http://localhost:5173` 的 Panel 访问。可用 `--port`、`--data-dir`、`--token-env` 覆盖默认值；重复的 `--allowed-origin` 或 `--allowed-host` 分别替换对应白名单。Bot、笔记、世界、cadence 和 MCP 诊断状态默认只读开放，交流走产品端点，无需再加 `--world` 或 `--cadence`。

需要从 TUI 编辑 TOML 时加 `--edit-config`，开放 `org.aurora.config:endpoints/configuration`。配置保存后正常重启生效；未加此参数时，F7 会提示配置入口未开放。

模型由 `profiles.toml` 与 `bindings.toml` 选择；MCP 服务、世界来源和 cadence 消费范围分别由对应 TOML 决定，缺失文件只补模板。新模板中的 MCP 服务、世界来源和 cadence 来源均为空，不自动接入外部服务或启动模型任务。已有配置选中了外部连接或自动转交来源时，启动会按配置建立连接并处理事件；笔记、归档、行动证据等能力仍由 Bot 配置开关决定。

另开终端，在仓库根目录运行 `pnpm tui`，自动加载根目录 `.env` 并读取 `AURORA_API_TOKEN`，已有环境变量优先。令牌只需在 `.env` 中配置一次；该命令只启动 TUI，后端需保持运行。连接地址沿用本地偏好，未保存偏好时默认为 `http://127.0.0.1:10270`；可用 `pnpm tui --connect http://127.0.0.1:10270 --instance main` 显式指定，也可用 `--token-env NAME` 指定其他令牌变量。离线无认证示例继续使用 `pnpm --filter @aurorabot/tui start`。

浏览器界面运行 `pnpm panel` 或 `uv run --locked aurora panel`，打开页面后自动使用根目录 `.env` 中的 `AURORA_API_TOKEN` 连接已有后端，默认地址为 `http://127.0.0.1:10270`，可通过 `AURORA_API_URL` 修改；仍保留手动连接入口。后端按 Ctrl+C 关闭并落盘；不要同时启动多个宿主使用同一数据目录。

### 在默认装配中观察时间和天气

工作区统一安装和 `scripts/bot.py` 已包含环境来源，无需修改宿主插件清单。独立安装使用 `aurora-world[environment]`；使用通用 CLI 时，在 host.toml 的 plugins 列表中显式加入 `aurora_world`、`aurora_world.configuration`、`aurora_world.environment`，保留原来的 bot、模型和 API 插件。默认装配会托管 world 配置选中的来源；没有启用 world 配置插件时保持原来的装配行为。

编辑 `<data-dir>/config/org.aurora.world/config.toml`。缺失文件的模板默认为空列表，启用以下来源时移除 `sources = []`，不要保留两个同名声明：

```toml
[[sources]]
source = "org.aurora.world:sources/environment/time"
source_id = "environment/time"
[sources.config]
mean_seconds = 1800.0
deviation_seconds = 300.0

[[sources]]
source = "org.aurora.world:sources/environment/weather"
source_id = "environment/weather"
[sources.config]
place = "南京"
latitude = 32.0617
longitude = 118.7778
interval_seconds = 900
timeout_seconds = 10
temperature_change_c = 3
```

地点名称和经纬度须一起修改；时间使用宿主本地时区。启动立即采样，主动看时间的间隔服从截断正态分布：均值 mean_seconds（默认 1800 秒）、标准差 deviation_seconds（默认 300 秒），范围为均值 ± 三倍标准差，默认 15～45 分钟；并非固定整点或半点。均值至少 60 秒且大于三倍标准差，标准差至少 1 秒。ctx 有效变化时刷新当前时间，同一秒合并，不重置主动采样的等待，不补发停机期间的周期。时间 payload.trigger 区分 startup/context/rhythm；原样转发模式只转交主动时间观察，决策模式也可评估随 ctx 刷新的时间。

移除某个来源项可单独停用，`sources = []` 停用全部来源，修改后重启生效，模板不覆盖已有配置。旧时间配置须删除 interval_seconds，改用上述两个字段。天气查询间隔至少 60 秒，总请求超时至多 30 秒。天气仍按周期查询，首次采样、相对上次已发布气温的绝对变化超过 temperature_change_c（默认 3°C）、天气代码或可用状态变化时才发布；恰好 3°C、仅时间戳或风速变化不发布，连续小幅温差累计比较。重复相同故障不重复发布，恢复时发布当前天气。

```powershell
uv run --locked aurora bot --edit-config
pnpm tui
```

两个命令分别在两个终端运行。`scripts/bot.py` 默认开放近期事件、环境观察与来源状态，TUI 状态页筛选 `org.aurora.world` 即可读取，F7 可编辑 TOML。观察包含采样时间、地点、温度、天气描述及数据有效时间；天气来自 [Open-Meteo 当前天气接口](https://open-meteo.com/en/docs)，属于天气模型数据，载荷保留提供方归属。超时、网络失败或无效响应写入 `status=unavailable` 和固定错误代码，不伪造天气；时间来源继续运行，下一个天气周期会重新采样。

环境采样更新 `org.aurora.world:state/environment`，按 source_id 区分，不进入普通事件数据库；启用 cadence 后，新观察可以参与唤醒。时间默认保留最新 1 条；天气保留最新已发布观察及一小时内的历史，合计最多 4 条。最新天气保留原始观测时间，不因天气稳定而消失，不代表刚刚重新发布。普通事件保存于 `namespaces/ns-org.aurora.world/events.sqlite3`，state/records 只提供近期文本视图，历史与去重不因呈现裁剪丢失。

统一保留规则写在文件根级 `[view]`（不要放进 `[sources.config]`）：

```toml
[view]
recent_seconds = 3600
max_chars = 32000
max_event_chars = 8000
time_count = 1
weather_count = 4
weather_seconds = 3600
refresh_seconds = 30
```

普通条目按整对象纳入，字符预算允许多出一个边界条目；超过单条预算时展示明确预览和 record_id，完整事件可用 `WorldRecords.get_by_id` 查询。数据库、事件服务和消费者均由宿主显式持有；`WorldRecords(ctx, storage)` 注入来源和 cadence，不能重新构造一个 `WorldRecords(ctx)` 来读取已有服务的内存。

已有 v1/v2 世界日志不会自动转换。先停止宿主，运行 `uv run --locked python -m aurora_world.migrate --root data`，将保留记录导入数据库并保留原消费身份，原快照备份到 `framework/ctx.before-world-database.json`。旧日志没有统一接收时间，迁移使用导入时刻；迁移前已裁剪的历史不会补造。原有来源配置的 retain_count/retain_seconds 手动改到 `[view]` 的 time_count/weather_count/weather_seconds。以后备份及恢复须同时包含数据库与 ctx 快照。

### 最小 cadence：原样转发世界记录

`scripts/bot.py` 已启用 cadence。使用通用 CLI 时，在默认 bot 的 `host.toml` 插件清单中显式加入 `aurora_world`、`aurora_bot.cadence`，保留已有的 bot、模型和配置依赖。来源按前节另行配置；只接收程序写入的世界记录时，无需启用 world 配置或环境插件。MCP 默认 bot 装配同样复用这一路径。

首次启动只补齐缺失的 `<data-dir>/config/org.aurora.bot/cadence.toml`。不配置 `[decision]` 时原样转发所有世界事件和环境变化，不再提供 `source_ids` 白名单。停用某个来源请修改 world 的 sources，暂停自动活动使用 bot_autonomy。

事件从数据库可用历史开始消费；环境按当前保留的观察消费，各来源独立记录锚点。每条新材料的 payload 原样形成引导，空闲时可启动运行，运行中继续接纳。环境不自动写入事件数据库，也不保证补发已经被保留策略裁剪的采样；需要可靠历史归档的来源仍可选择 presentation = "events"。回执保留来源、材料身份和类型，接纳不代表业务完成。直接交流继续使用同一 AgentRuntime。

```powershell
uv run --locked aurora bot --edit-config
```

`scripts/bot.py` 默认启用 cadence 并开放观察状态。TUI 状态页读取 `org.aurora.bot:state/cadence`，location 的 instance_id 与 bot 配置一致；其中 position 为扫描位置，pending 为尚无确定回执的原消息，receipts 保存消息、guidance_id、sequence 和 run_id。F7 可编辑来源选择，正常关闭后重启生效。已有消费状态绑定了原来源集合，改变集合会暂停，不能通过改配置悄悄改变消费范围。

`error=TransferUncertain` 表示须核对 pending 是否已经进入 agent；`CursorInvalid` 表示日志换代、缺失或裁剪缺口。暂停不阻断直接交流，也不会因重启自动解除。核对时先停止宿主并保留完整快照，对照 world、pending、receipts 与 agent 数据；不能仅凭文本相同认定已投递。首版没有自动核对或重置命令，须由宿主明确决定修复后的消费状态，不能直接删除游标来重放。

完整回执随宿主异步保存，暂不自动裁剪；不能据此承诺崩溃时恰好一次执行。world 的去重覆盖数据库历史，呈现窗口外的同身份重投仍返回原记录。离线回归为 `uv run --locked pytest packages/aurora_bot/tests/unit/test_cadence_state.py tests/e2e/test_cadence.py -q`；live_workshop 已完成正式替换，双路径与恢复验收见 `tests/e2e/test_live_workshop.py`。

### 决策 cadence：受控随机时钟与类型化判断

在独立数据目录中配置决策模式。省略 `[decision]` 仍使用上节的原样转发；添加该段后，cadence 每次等待一个有上下限的随机间隔，再让 choice 模型选择 `observe`、`attend_events` 或 `review_work`。随机数只决定判断时机，不参与模型选项或概率的抽样。第一次判断也等待间隔，重启不补发离线期间的判断。

在 `<data-dir>/config/org.aurora.adapter/model/profiles.toml` 中增加决策 profile，保留原聊天 profile：

```toml
[decision]
adapter = "org.aurora.adapter:adapters/model/litellm_choice"
model = "typesafe/jev-latest"
base_url = "https://jevmodel.org"
credential = "JEVMODEL_API_KEY"
```

`base_url` 为你选择的 SystemOne 兼容服务根地址。以上对应 [jevmodel.org 接入文档](https://jevmodel.org/zh/docs/)，该服务与 TypeSafe 官方服务的账户及凭证不能互换；使用 TypeSafe 官方服务时按其接入方式配置地址和凭证。协议转换复用 [LiteLLM Decisions](https://docs.litellm.ai/docs/decisions)，现有锁定版本已支持，不需要增加代理进程或另装 SDK。真实调用需要服务账户；普通回归只使用假模型与模拟传输。

在同目录的 `bindings.toml` 中增加 `cadence = "decision"`，保留原 `reasoning` 等绑定。凭证值通过运行环境注入，不写入 TOML。决策 profile 不接受聊天模型的 `capabilities`；聊天和 choice 工厂不能混用。

`<data-dir>/config/org.aurora.bot/cadence.toml` 示例：

```toml
[decision]
model_role = "cadence"
active_seconds = 5.0
idle_seconds = 180.0
half_life_seconds = 60.0
jitter_ratio = 0.2
timeout_seconds = 15.0
max_chars = 12000
```

所有世界来源的事件和环境变化均可参与决策，同时读取已启用的本实例工作笔记和行动证据。若需检查笔记，在 bot 的 config.toml 中设置 `[notes] enabled = true`。`review_work` 没有可见笔记、`attend_events` 没有未投递事件或环境变化时，不产生引导。决策模型不读取完整聊天历史、任意 ctx、配置或凭证。

ctx 的有效变化提高活动度，判断间隔随活动度在 active_seconds 和 idle_seconds 之间变化，再施加 jitter_ratio 的随机浮动；同值写入不产生刺激。默认一次外部变化将空闲等待提前到约 11～17 秒，连续变化可接近 5 秒，安静时活动度按 half_life_seconds 衰减，最终恢复约 144～216 秒的低频判断。连续输入只提前已有期限，不无限推迟判断；判断串行执行，开始时间至少相隔 active_seconds，推理期间的新刺激保留到下一轮。

时间刷新、cadence 记账及 Bot 运行状态允许反馈，每次反馈强度减半，低于 0.01 后不再加速；新的外部变化重置反馈强度。运行中的其他 ctx 变化按反馈处理，但世界事件和主动环境变化仍是新刺激。时间自行写回会收到上下文通知，同秒合并使直接写回收敛。调度使用单调时钟，墙钟只用于观察时间；节律不持久化，恢复后从当前上下文重新起步。旧 min_seconds/max_seconds/cooldown_seconds 配置须删除，不再有十分钟引导冷却，last_guided_at 仍作为历史事实保留。超时、无效选项或调用失败暂停为 `DecisionFailed`，没有默认行动、自动重试或静默回退。

视图复用 BusinessContextView，读取全部世界来源并隔离实例笔记。max_chars 限制统一 ChoiceRequest 的完整 JSON 字符数，包括 state、instructions 和 criteria，不是供应商 token 或实际 HTTP 大小；视图单独预留信封空间，必要材料仍超限时暂停。`observe` 仅更新观察，不表示事件完成；窗口内未投递材料可以再次评估。超过窗口或预算的事件不会逐条补发，要求历史事件可靠逐条转交时继续使用原样转发模式。

`attend_events` 和 `review_work` 由固定模板形成带决策身份、观察时间和业务视图的引导，经原 AgentRuntime 提交；Bot 忙碌时可接纳新引导，取消收尾期间被明确拒绝的投递留待下一次判断。Bot 可以判断无需行动。事件全局位置与每个环境来源的独立锚点抑制旧材料重复引导；笔记是否再次检查由选择模型判断，笔记内容和投递回执均不证明业务完成。

`org.aurora.bot:state/cadence` 的决策快照为 version=4，分别保存观察 position/observation、事件引导位置 event_position、环境引导位置 environment_positions、last_guided_at、pending 和最近 64 条 receipts。回执保留决策结果、材料引用、guidance_id、sequence 和 run_id，旧回执裁剪不回退事件位置；这不是完整审计日志。pending 保留待核对的具体引导；未知投递及回执保存失败暂停为 `TransferUncertain`，恢复不重投。快照由宿主异步保存，不承诺崩溃下恰好一次投递。

两种模式的快照不可互换；检测到已有另一模式的状态会拒绝启动，不自动改写或删除用户数据。首次试用使用独立数据目录；当前不提供跨模式迁移或暂停状态的自动修复。旧 version=1/2 消费状态在同一模式下升级为 version=3/4，保留游标、pending、回执和故障；只移除来源绑定及已取消的 SelectionChanged 暂停。旧配置中的 source_ids 必须删除，不会静默忽略。升级前备份数据目录；升级后的快照不能直接交给旧程序恢复。关闭时先取消并等待判断，再关闭决策连接，Bot 的执行与工具继续由原所有者收尾。

决策 cadence 离线回归：

```powershell
uv run --locked pytest packages/aurora_adapter/tests/contract/test_litellm_choice.py packages/aurora_bot/tests/unit/test_cadence_state.py tests/e2e/test_cadence_decision.py -q
```

### Bot 的计划唤醒与自身控制

在 `<data-dir>/config/org.aurora.bot/config.toml` 显式启用后重启：

```toml
[self_control]
enabled = true
```

默认关闭，已有用户文件不被覆盖。功能由 `aurora_bot.assembly` 提供，不新增插件；计划唤醒无需启用 world 或 choice 模型。启用 cadence 时，两者共用自动引导暂停开关，所有引导仍交给同一个 AgentRuntime。

| 模型工具 | 用途 |
| --- | --- |
| `bot_status` | 查询当前运行、UTC 时间、自动引导开关、计划数量、下次唤醒及计划等待故障 |
| `bot_autonomy` | `paused=true` 暂停普通 cadence 和计划唤醒；`false` 恢复，不清除既有故障 |
| `bot_finish` | 本轮全部工具与结果观察完成后正常结束，不再发起下一轮推理 |
| `wake_schedule` | 创建或更新一次性计划，支持相对秒数或带时区的绝对时间 |
| `wake_list` | 分页读取自己的完整计划与回执；默认每页 10 条，最多 20 条，使用 next_after 继续 |
| `wake_cancel` | 按版本取消尚未提交的计划；不撤销已经接纳的引导 |

例如 Bot 通过 `wake_schedule` 登记十分钟后的检查：

```json
{
  "wake_id": "check_delivery",
  "expected_revision": 0,
  "delay_seconds": 600,
  "late_seconds": 3600,
  "text": "核对先前发送的结果，未知结果先查证，不直接重发。"
}
```

也可以用 `"at": "2026-11-09T10:00:00+08:00"` 替代 delay_seconds，两者必须二选一，时间须在未来 30 天内。late_seconds 是到期后的有效期，默认一小时，最多一天；超过有效期标记 expired，重启或恢复自动引导时不补发。有效期内已到期的计划会提交一次引导，忙碌时进入当前运行，取消收尾期间明确拒绝的提交等待后重新检查有效期。计划不经过 choice 判断或普通 cadence 的冷却。

创建使用 expected_revision=0；更新或取消先用 wake_list 取得当前 revision。系统投递、过期和恢复也会推进版本，旧版本返回 wake_conflict。每实例最多 128 条计划，终态记录继续占用容量，可显式更新已有计划；文本最多 4000 字符。工具不接受其他 instance_id，不允许通过 tools 配置重复装配。

安排好计划后可调用 bot_finish 结束本轮，等待未来唤醒。该工具应放在本批最后：同批其他工具仍会执行，工具结果完整写回上下文及已启用的行动证据。后来到达的引导保留给同一运行时的后续激活。正常结束不暂停 cadence；若需要暂停所有自动活动，单独调用 bot_autonomy。暂停后计划也不会唤醒 Bot，直接交流仍可发起运行并让 Bot 调用 bot_autonomy 恢复；直接交流本身不隐式恢复开关。

`org.aurora.bot:state/self_control` 按 `location={instance_id}` 保存 version=1 状态，包含 paused、error 和计划。计划的 submitted 及 receipt 只表示引导接纳，不证明业务完成；pending 在恢复时标记 uncertain，未知提交和回执写入失败不自动重投。uncertain 不允许直接覆盖，须核对后显式取消；取消不撤销可能已发生的动作。计划等待的基础设施错误保留 WakeupFailed，普通暂停/恢复不清除它或 cadence 的故障。

状态依赖宿主异步快照，不承诺崩溃下恰好一次投递。关闭先停止计划等待和自动输入，再关闭运行、工具、模型并最终落盘。关闭 self_control.enabled 保留已有状态但不运行计划服务或提供控制工具；其中的暂停门控也不启用。新 ID 不替换旧定义，旧快照无需迁移，含新状态的快照需使用登记该 ID 的版本恢复。`scripts/bot.py` 已将该状态作为只读观察键开放，不新增 HTTP 控制端点或宿主退出/重启工具。

离线回归：

```powershell
uv run --locked pytest packages/aurora_bot/tests/unit/test_self_control_state.py tests/e2e/test_self_control.py packages/aurora_agent/tests/unit/test_react_agent.py -q
```

## MCP 独立客户端验收

M4.B1 提供 `aurora-adapter[mcp]`；工作区开发依赖已包含该 extra，统一产品安装不自动启用 MCP。通过现有测试夹具启动并关闭一个本机 MCP 服务和独立宿主：

```powershell
uv run --locked python tests/fixtures/mcp_roundtrip.py build/mcp-acceptance
```

夹具只在指定验收目录创建测试配置，完成真实 Streamable HTTP 能力发现、测试工具往返、资源读取、断线诊断和最终落盘；不访问真实供应商或用户模型。它不是新增产品示例入口，不要将验收目录指向已有用户数据。

自定义宿主显式启用 `aurora_config` 和 `aurora_adapter.mcp`，登记生命周期插槽，装配 `configuration_component` 与 `MCPClients(ctx, hooks).component()`。消费者依赖默认组件身份 `aurora_adapter/mcp`，在 prepare 完成后借用：

```python
async with clients.connection("local") as client:
    tools = await client.list_tools()
```

SDK 对象仅在适配层使用，不存入 ctx 或传给 world/agent。借用期间不要跨任务退出或自行关闭客户端，退出后不要保留引用继续使用；长期消费者在自己的 stop 阶段收束。停止整个宿主会封闭借用入口并取消剩余借用，等待它们的 finally 完成后才释放连接。

缺失配置文件会在 `<data-dir>/config/org.aurora.adapter/mcp.toml` 生成 `schema_version = 2` 与空 `[servers]` 模板。下面是一份可运行的连接声明；服务名 `local` 就是原 connection_id，名称不表示传输类型：

```toml
schema_version = 2

[servers.local]
type = "remote"
url = "http://127.0.0.1:8000/mcp"
protocol = "2026-07-28"
required_capabilities = ["tools", "resources"]
timeout = { startup = 10, catalog = 30, execution = 30, shutdown = 10 }

# [servers.local.headers]
# Authorization = "Bearer {env:AURORA_MCP_TOKEN}"
```

headers 支持 `{env:NAME}` 引用和固定前缀；Authorization 等凭证字段不能填写纯字面量。引用只在 prepare 创建连接时解析，不进入 ctx、快照或日志；缺失或非法值报告服务名与字段位置。`enabled = false` 不创建连接、解析凭证或登记工具。地址不可包含凭证、查询串、片段或环境引用；修改配置后重启生效。

B5.2–B5.3 支持 HTTP(S) Streamable HTTP 和 stdio 的 legacy、auto 和固定 2026-07-28 三种策略，默认 legacy。允许的实际版本为 2025-11-25 与 2026-07-28；legacy 直接旧握手，auto 由 SDK 探测并按策略回退，固定新版显式 discover 后检查能力。HTTP 401/403、5xx、重定向和损坏 JSON 明确失败，不掩盖为成功回退；RPC 错误本身不作为版本证据。local 与 remote 使用相同协商及工具执行路径。SDK 固定 2.3.0，不自动处理多轮输入或重放工具动作。

本地服务由宿主显式装配 `MCPClients(ctx, hooks, workspace_root=workspace_root)`；workspace_root 是宿主选定的项目目录，不能把任意调用时 cwd 当作默认根。相对 cwd 基于该根目录，prepare 检查目录存在；不填写 cwd 时使用工作区根。command 是参数数组，不拼接 shell 字符串；环境变量只继承 SDK 基础集合，再覆盖显式 environment，不修改宿主环境。

```toml
schema_version = 2

[servers.files]
type = "local"
command = ["python", "server.py"]
cwd = "tools"
protocol = "legacy"

[servers.files.environment]
APP_TOKEN = "{env:APP_TOKEN}"

[servers.files.tools]
include = ["read_file"]
aliases = { read_file = "files_read_file" }
```

stdio 的 stdout 仅允许 JSON-RPC，每条消息上限 4 MiB，非法 JSON、未结束消息超限和 EOF 都明确失败；原始 stderr 丢弃，避免洪泛阻塞或泄露凭证。关闭先关 stdin、限时等待，再回收所属 Windows Job/POSIX 进程组，根进程已退出也会清理其所属后代。启动失败不自动重启，工具动作不自动重发；后台观察能报告本地进程退出，但不将 ready 当作永久健康保证。

根级 `[timeout]` 提供公共超时，各服务逐字段覆盖；startup/catalog/execution/shutdown 默认分别为 10/30/30/10 秒，限制握手、完整目录发现、单次工具调用和每服务每次 stop/clean 等待。工具执行同时受 agent 外层超时约束。SDK 请求与 HTTP 空闲读取上限取前三者的最大值，各操作通过自己的外层预算提前结束。关闭等待超时不取消正在执行的 finally，可再次等待；真正的关闭异常需诊断后重建宿主。

客户端状态使用 `org.aurora.adapter:state/mcp/clients`，location 为 `{"owner": "aurora_adapter/mcp", "connection_id": "local"}`；error_location 仅包含安全字段位置；configured_protocol 表示配置策略，negotiated_protocol 替代旧 protocol_version，negotiation_attempts 最多记录四次协商的方法、HTTP 状态和数值 RPC 错误码。状态非持久，无快照迁移；ready 表示启动准备完成，没有后台健康探测；失败不自动重连或重放请求。

旧 connections/tools 布局及混合布局均拒绝加载。先生成独立候选及规范化差异，审阅后自行应用；命令不覆盖任何已有文件、不读取凭证、不连接服务：

```powershell
uv run --locked python -m aurora_adapter.mcp.migrate data/config/org.aurora.adapter/mcp.toml --output build/mcp-v2-candidate.toml
```

迁移保留服务名、固定新版策略、工具名称与公共 ID；没有旧工具选择的连接转为 `include = []`。同一远端工具对应多个旧别名时停止转换。保留 bot 的显式工具选择及实例身份、world 的 connection_id 和业务快照，不合并多个 bot/工具实例；需核对 bot 的 tool_timeout。候选新增 shutdown=10 秒，关闭超时后仍须继续等待清理。差异忽略注释和排版，不回显原文件注释。

产品入口尚不自动装配 MCP；世界通知和工具分别通过下面的桥接组件显式装配。添加插件清单仅登记定义，不会自动连接服务。

### MCP 工具桥

安装 `aurora-adapter[mcp-tools]`，显式启用 `aurora_config`、`aurora_adapter.mcp`、`aurora_agent.tools`、`aurora_adapter.mcp.tools`；使用默认 bot 时同时启用其原有插件。只使用工具桥不需要安装或启用 world、bot、CLI、API。

在 `<data-dir>/config/org.aurora.adapter/mcp.toml` 的相应服务下添加：

```toml
[servers.local.tools]
include = ["echo"]
aliases = { echo = "local_echo" }
```

include/exclude 使用精确远端名称，exclude 优先；aliases 将已选远端名称映射到本地模型名称。名称须为小写字母开头的小写字母、数字或单下划线分隔名称，最长 64 字符。例如 `local_echo` 对应公共 ID `org.aurora.adapter:tools/mcp/local_echo`。不同服务的同名工具可指定不同本地名称；名称重复、远程工具缺失或参数 schema 无效会使启动失败。

工具桥默认 `include = ["*"]`，对声明 tools 能力的服务发现全部工具；无工具能力且没有显式选择要求的服务保留供其他消费者使用。未指定 aliases 的工具使用 `mcp_<server_slug>_<tool_slug>_<digest>`，digest 为原始服务名和远端工具名紧凑 UTF-8 JSON 的 SHA-256 前 12 位；slug 分别截取到 16/24 字符，名称最长 58 字符，算法以 v2 固定。自动名称、显式别名、既有本地工具名称与公共 ID 统一检查冲突，失败时不登记部分目录。`include = []`、空 exclude 表示不发现、不登记该服务的工具。修改配置或服务端目录后须重建宿主，不在运行中热改集合。

宿主将工具发现列为消费者的前置依赖：

```python
from aurora_adapter.mcp import MCPClients
from aurora_adapter.mcp.tools import MCPTools

clients = MCPClients(ctx, hooks)
tools = MCPTools(registry, ctx, hooks, clients)
components = [
    configuration_component(registry, ctx, hooks, storage),
    clients.component(),
    tools.component(),
    *assembly.components(depends_on=(tools.instance_id,)),
]
```

这里 `assembly` 是既有 `DefaultAssembly` 实例。它在发现完成后才检查工具并创建模型；bot 的配置选择相应工具（没有其他工具时删除模板中的 `tools = []`）：

```toml
[[tools]]
tool = "org.aurora.adapter:tools/mcp/local_echo"
instance_id = "echo"
```

无 bot 的宿主可从登记的 ToolSpec.factory 创建 ToolInstance，再将 plug 接入 ToolExecutor；完整代码见 [mcp_tools_roundtrip.py](../../../tests/fixtures/mcp_tools_roundtrip.py)。工厂不接受额外实例配置，连接和远程名称由 MCP 配置确定。实例关闭仅封闭自身入口，在途调用由消费者收束；共享连接由 MCPClients 最后释放。

结果保留 MCP JSON 字段（如 `content`、`structuredContent`、`isError`），包括图像、资源链接等内容块；桥不会自动下载附件。业务错误为 `mcp_tool_error`，其内容仍进入失败观察；协议错误为 `mcp_protocol_error`，只保留数值错误码。请求超时为 `mcp_timeout`，传输中断后的结果未知为 `mcp_result_unknown`，无有效结果为 `mcp_invalid_result`，尚未提交为 `mcp_unavailable`；额外交互为 `mcp_input_required`，不自动续发。外层执行器超时/取消沿用 `timeout`/`cancelled`。超时、取消及结果未知均不表示远端动作没有执行，不自动重试；调用始终通过 agent 的参数校验与 before_call/after_call。

本机验收命令（夹具创建测试配置，目录勿指向已有用户数据）：

```powershell
uv run --locked python tests/fixtures/mcp_tools_roundtrip.py build/mcp-tools-acceptance
uv run --locked python tests/fixtures/mcp_tools_roundtrip.py build/mcp-bot-acceptance --bot
uv run --locked python tests/fixtures/mcp_tools_roundtrip.py build/mcp-legacy-acceptance --protocol legacy
uv run --locked python tests/fixtures/mcp_tools_roundtrip.py build/mcp-auto-acceptance --protocol auto
uv run --locked python tests/fixtures/mcp_tools_roundtrip.py build/mcp-stdio-acceptance --transport local --protocol legacy
uv run --locked python tests/fixtures/mcp_tools_roundtrip.py build/mcp-stdio-bot-acceptance --transport local --protocol auto --bot
uv run --locked python tests/fixtures/mcp_tools_roundtrip.py build/mcp-auto-tools-acceptance --transport local --automatic --bot
```

两条路径均只访问本机测试 MCP 服务，默认 bot 使用假模型。外部真实 MCP 服务兼容性验证另行安排；B3 已完成工具桥与世界通知桥的 HTTP、stdio、混合连接共享关闭验收，使用正式产品装配和假模型。

### MCP 默认 bot 产品预设

安装 `aurora-adapter[mcp-bot]` 和所需宿主 `aurora-cli`；API 另需 `aurora-api`。工作区开发环境已有这些包。执行一次预设，填写生成的模型 profiles/bindings 与 MCP servers，即可通过正式入口使用工具，不需要手写 Python 装配：

```powershell
uv run --locked python -m aurora_adapter.mcp.preset .aurora-mcp --api --world
# 填写 .aurora-mcp/config 下的模型和 MCP 配置后：
uv run --locked aurora --root . -d .aurora-mcp org.aurora.bot:commands/run/submit "使用可用工具完成任务" --instance-id main
uv run --locked aurora --root . -d .aurora-mcp serve --port 8765 --endpoints '["org.aurora.bot:endpoints/conversation"]'
```

instance_id 应与 `org.aurora.bot/config.toml` 一致。`--world` 显式启用世界配置和 MCP 来源插件，来源列表仍需按下一节填写；`--api` 显式启用 API 插件。只需工具时可省略两项。预设不创建连接、子进程或模型，不覆盖已有文件。已有 host.toml 与预设不同时显示差异，写入 `host.mcp.toml` 并返回 2；审阅并显式应用候选后启动。候选已存在且不同则报错保留。

预设选择 `org.aurora.adapter:assemblies/mcp/default_bot`，先发现工具，再与 bot 的本地工具选择合并。自动补入工具的实例身份使用工具 ID 的 local_path；已显式选择的 MCP 工具保留原实例身份，不重复添加。运行期目录不写回 TOML 或配置状态，名称/实例冲突仍拒绝启动。标准装配工厂新增 workspace_root 关键字，第三方工厂须同步接收；它来自 `--root`，与数据目录独立，stdio 默认 cwd 和相对路径均以此为准。

### MCP 世界通知桥

世界来源目前使用 2026-07-28 的订阅契约；即使旧版连接声明 resources，来源也会明确报 unsupported_subscription_protocol，不尝试未实现的旧订阅。该连接仍可供工具使用。

安装 `aurora-adapter[mcp-world]`，宿主显式启用 `aurora_config`、`aurora_adapter.mcp`、`aurora_world`、`aurora_world.configuration` 和 `aurora_adapter.mcp.world`。保留上述 MCP 连接配置，使用共享 MCPClients，并用 `mcp_world_component` 替代通用 configured_sources_component；不要在同一 ctx 重复装配两个 world 来源所有者：

```python
from aurora_adapter.mcp import MCPClients
from aurora_adapter.mcp.world import mcp_world_component
from aurora_world import WorldRecords

clients = MCPClients(ctx, hooks)
records = WorldRecords(ctx, storage)
components = [
    configuration_component(registry, ctx, hooks, storage),
    clients.component(),
    records.component(hooks),
    mcp_world_component(ctx, hooks, clients, records, depends_on=("aurora_world/records",)),
]
```

在 `<data-dir>/config/org.aurora.world/config.toml` 的现有 sources 列表中增加来源。若文件只有 `sources = []`，先移除该行；已有环境来源可以与 MCP 来源共存于同一列表：

```toml
[[sources]]
source = "org.aurora.adapter:sources/mcp/resources"
source_id = "external/resources"
[sources.config]
connection_id = "local"
buffer_size = 64
max_content_bytes = 1048576
watch_tools = false

[[sources.config.resources]]
uri = "board://current"
mode = "resource"

[[sources.config.resources]]
uri = "events://latest"
mode = "event"
```

URI 精确匹配，不自动读取服务端报告的其他 URI 或子资源。mode 默认为 resource，读取当前资源内容；notification 只存变化提示、不读取；这两种模式均生成本地观察身份，不把 URI 或内容哈希当作稳定事件 ID。event 要求服务端返回单个文本资源，其文本是严格 JSON，例如 `{"message_id":"event-42","payload":{"text":"原文"}}`；缺失身份或额外字段会使来源失败。同连接、URI、message_id 在同 source_id 下重投同文不会重复记录，异文明确冲突。切换到另一逻辑上游时应选择新的 source_id 或 connection_id。去重限于 world 仍保留的记录。

订阅确认后才开始接纳，不在启动时自动读取资源或补发停机期间消息。MCP 资源变化是“可能需要重新读取”的提示，SDK 会合并尚未消费的同 URI 通知；读取时得到的是最新值，event 模式也不能据此保证完整业务事件历史。需要逐条可靠投递的上游必须另外提供可追读事件日志契约。

桥接状态位于 `org.aurora.adapter:state/mcp/world`，location 为 `{"source_id":"external/resources"}`。identity_modes 明确是本地观察还是来源消息身份，accepted/duplicates 表示 world 数据库接纳及去重结果。watch_tools 只设置 tools_dirty，不把目录变化写成世界输入，也不热更新工具。缺失能力、订阅未确认全部选择、身份错误、读取失败、连接丢失及队列溢出均有固定错误码，并封闭对应来源；不自动重订阅或重放。修正后需正常重启宿主。

buffer_size 限制适配器等待处理的通知数，不包括当前一项读取；max_content_bytes 限制读取后可接纳的序列化内容大小，不是 HTTP 响应下载上限。SDK 另有 1024 项不同待消费事件的上限，其丢流报告为 subscription_lost。HTTP 空闲读取上限取服务 startup/catalog/execution 超时的最大值，长时间无消息的服务应发送流心跳或配置相应超时。停止来源会等待订阅与在途读取收束，释放借用而不关闭共享客户端；已收到但尚未接纳的观察会记入 discarded，并报告 stopped_with_pending 或对应故障及日志。桥接诊断不持久化，重启不会恢复这些待处理通知；已接纳的 world 记录由宿主最终落盘。

独立验收夹具在本机启动真实 MCP 服务，验证通知、资源读取、稳定事件去重、宿主恢复、来源失败隔离和断流：

```powershell
uv run --locked python tests/fixtures/mcp_world_roundtrip.py build/mcp-world-acceptance
```

该命令只创建测试服务，但会写指定目录的验收配置，请使用独立目录。同一目录再次运行会验证保留记录的去重与新观察追加。它不调用真实模型，不是新的产品示例入口。

## 真实模型验收

真实模型手工验收使用当前 CLI。先按上文在独立数据目录中配置宿主插件、默认装配、模型 profile、角色绑定及所需工具，并通过环境变量提供凭证。以下以已配置好的 `build/model-acceptance` 为例；执行会调用配置的供应商及模型选择的工具。

```powershell
uv run --locked --env-file .env aurora --data-dir build/model-acceptance org.aurora.bot:commands/run/submit "请回复一条简短的验收消息" --instance-id main
```

按需在 bot TOML 中切换 `streaming`，检查 CLI 的运行终态和模型输出；需要工具验收时，使用该目录中显式启用的工具。重复启动同一目录可检查历史恢复，恢复本身不自动激活 agent。配置与快照不保存运行期凭证。

常规工具往返、流式/完整响应、收尾与重启回归由 [默认装配测试](../../../tests/e2e/test_default_assembly.py) 使用假模型或模拟传输验证，无需调用真实供应商。

## 数据目录

快照位于 `<data-dir>/framework/ctx.json`，各示例不共用数据目录，也不并发访问同一目录。恢复要求所有状态定义已经登记；运行时不映射旧 ID，也不自动续跑任务。验证新命名空间时请使用新的数据目录，已有数据如需保留应先备份并离线转换对应 ID。

`build/` 是 Git 忽略的本地输出目录。对任意保留入口使用 `--help` 可查看完整参数。
