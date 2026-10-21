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

输入框只填写操作参数。点击“执行”或按 F5 / Ctrl+Enter 调用；点击“载入示例”或按 Ctrl+R 恢复示例，按 Ctrl+Q 退出。选择操作和载入示例不会执行调用，切换模块保留本次会话状态。执行期间禁止重复提交，退出时等待当前调用完成并释放资源。`--tui` 需要交互终端，输出始终缩进显示。

默认行交互模式下，添加 `--pretty` 可将响应缩进显示，添加 `--module kernel` 可预先选择模块：

```bash
uv run aurora playground --pretty --module kernel
```

可用简写命令查询和调用，无需反复输入完整请求：

```text
list
use kernel
describe increment
increment {"amount":3}
state
exit
```

终端支持 Tab 补全命令、模块和操作名，↑/↓ 调取当前会话历史，以及多行 JSON 输入或粘贴；JSON 未闭合时回车续行，闭合后回车提交。历史只保存在内存中。`help` 查看简写用法。

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

入口还支持 `cli` 模块，可用 `{"action":"describe","module":"cli"}` 查询。CLI 仅执行演示命令，返回退出码、终端输出及结构化结果。交互无需模型、网络或个人配置。输入错误返回 JSON，之后可继续调用；执行失败不会自动回滚或重试。

默认标准输出每行只包含一条 JSON 响应，可用于管道处理；`--pretty` 改为多行输出，不再是 JSON Lines。管道输入始终逐行读取。`Ctrl+D` 结束输入，`Ctrl+C` 中断退出。也可单独运行预设场景：

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

插件示例、回调约定与执行限制见仓库中的 `src/aurora_bot/engine/README.md`。替换整个认知执行策略仍通过 `CognitionRunner` 能力完成。
