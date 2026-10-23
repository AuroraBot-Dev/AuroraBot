---
order: 4
---

# Namespace 与 hook

Namespace 用于组织模块的状态与调用点，hook 用于为调用点提供实现。它适合组合通用 Python 功能；向 Bot 提供可发现的工具和领域操作时，参见[模组开发](./core-development)。

## 使用边界

- 注册 hook 不会自动触发执行，需要调用方显式调用对应入口。
- 共享上下文保存进程内状态，不代替持久记录，也不提供权限隔离。
- 通用 hook 不会自动成为模型可用工具，工具可见性需要单独配置。

## 运行 Playground

在仓库根目录启动终端交互，用 JSON 输入调用模块并查看结构化结果：

```bash
uv sync --locked --group dev
uv run aurora playground
```

`playground` 后面的参数直接透传，`aurora playground --help` 查看帮助。该命令需要源码仓库及开发依赖；从其他目录运行时，用 `aurora --root /path/to/AuroraBot playground` 指定仓库。也可继续使用 `uv run python -m playground`。

使用 Textual 界面可选择模块和操作、编辑参数 JSON，并切换查看格式化结果和接口说明：

```bash
uv run aurora playground --tui --module kernel
```

顶部按钮打开可搜索的模态选择框，Ctrl+K 选择模块，Ctrl+O 选择操作，Ctrl+P 打开命令面板；方向键选择、Enter 确认、Esc 取消。通常输入框只填写参数 JSON；选择 `cli.execute` 后直接填写 `aurora ...` 命令。点击“执行”或按 F5 / Ctrl+Enter 调用，Ctrl+R 恢复示例，Ctrl+Q 退出。选择操作和载入示例不会执行调用，切换模块保留本次会话状态。执行期间禁止重复提交，退出时等待当前调用完成并释放资源。清空输入后键入 `/` 可打开命令面板，输入关键词筛选，Tab / Enter 填入命令，再按 Enter 执行；命令参数可用 Tab 继续补全，Esc 关闭。`--tui` 需要交互终端。

响应默认缩进显示，并在终端提供 JSON 语法高亮；`--no-pretty` 同时关闭缩进和高亮，输出紧凑 JSON。添加 `--module kernel` 可预先选择模块：

```bash
uv run aurora playground --module kernel
```

交互命令以 `/` 开头，无需反复输入完整请求：

```text
/list
/use kernel
/describe increment
/increment {"amount":3}
/state
/exit
```

行终端输入 `/` 自动显示带说明的补全列表，继续输入按命令前缀或名称片段筛选；`/use `、`/describe ` 可补全模块与操作名。↑/↓ 选择，Tab / Enter 填入候选，随后 Enter 提交，Esc 取消补全。未打开候选列表时，↑/↓ 调取当前会话历史。支持多行 JSON 输入或粘贴；JSON 未闭合时回车续行，闭合后回车提交。历史只保存在内存中。`/help` 查看简写用法。

也可以输入完整 JSON 请求。先查询模块与操作格式，再按示例调用：

```json
{"action":"list"}
{"action":"describe","module":"kernel","operation":"increment"}
{"module":"kernel","operation":"increment","input":{"amount":3}}
{"module":"kernel","operation":"state"}
{"module":"kernel","operation":"reset","input":{"extension":false}}
{"action":"exit"}
```

`describe` 返回操作说明、输入与输出 JSON Schema，以及可直接执行的示例。默认启用双倍增量扩展，因此新会话传入 `3` 返回 `6`；重置时关闭扩展后，传入 `3` 返回 `3`。状态保留至重置或退出，各次启动独立。

可直接输入真实 CLI 命令，也可用 `cli.execute` 提供参数数组：

```text
/aurora --help
/aurora config --missing
/cli.execute {"argv":["--version"]}
```

真实命令读取项目配置与 CLI 插件，默认项目目录为 Playground 工作目录，也可在命令中使用顶层 `--root` 指定。命令通过独立进程执行，会产生真实效果；字符串按引号分词，不经过 shell。结果返回 `exit_code`、`stdout`、`stderr`、`result` 和 `timed_out`；标准输出整体为 JSON 时才填入解析后的 `result`。命令是否成功由 `exit_code` 表示。输入错误返回 JSON，之后可继续调用；执行失败不会自动回滚或重试。

执行默认等待 60 秒，可在 `cli.execute` 参数中通过 `timeout_seconds` 设置 1～3600 秒；超时终止命令，返回退出码 `124` 与部分输出，已发生的效果可能保留。标准输入默认立即结束，可通过 `stdin` 提供预设输入；输出在命令结束后返回，不提供实时输出或交互式终端，需要持续交互的命令请在独立终端运行。

`cli.demo` 单独提供内存演示命令，例如 `/cli.demo {"argv":["demo","greet","Aurora"]}`；Kernel 计数器和 Agent 本地模型、工具用于离线观察执行机制。用 `/describe cli.execute` 或 `/describe cli.demo` 查询完整参数。

管道处理时使用 `--no-pretty`，标准输出每行一条紧凑 JSON 响应；默认输出多行 JSON，重定向时不带颜色转义码。管道输入始终逐行读取。`Ctrl+D` 结束输入，`Ctrl+C` 中断退出。也可单独运行预设场景：

```bash
uv run python -m playground.examples.kernel hooks --amount 5
uv run python -m playground.examples.kernel context
uv run python -m playground.examples.kernel lifecycle
uv run python -m playground.examples.kernel lifecycle --fail-run
uv run python -m playground.examples.kernel validation
```

`hooks` 展示依赖排序、三种调用模式、嵌套调用与宿主独立状态；`context` 展示容器快照、跨空间事务、冲突和服务引用；`lifecycle` 打印阶段计划、实际回调与逆序清理，`--fail-run` 演示后台故障交付；`validation` 展示缺失依赖、依赖环和同优先级冲突在初始化之前失败。输出包含 ctx 版本、变更来源与字段，可修改脚本中的声明和优先级后重新运行。

声明、调用与生命周期的代码说明见仓库中的 `src/aurora_kernel/README.md`。

## 扩展 Bot 推理

默认认知执行器支持替换记忆召回、上下文装配和推理实现，也支持订阅步骤与工具执行前后的通知。插件通过普通 namespace hook 接入，放入 `extensions/plugins/` 后重启生效。扩展不会自动成为模型可用工具。

可先运行离线示例，对比默认实现与自定义 hook：

```bash
uv run python -m playground.examples.react
uv run python -m playground.examples.react --default
```

插件示例、回调约定与执行限制见仓库中的 `src/aurora_bot/engine/README.md`。模型入口为 `aurora:kernel/module/ai:complete`，认知入口为 `aurora:kernel/module/engine:execute`；执行由独立 Agent Run 驱动，不包含父子 Agent 调度。
