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
uv run python -m playground
```

每行输入一个完整的 JSON 对象。先查询模块与操作格式，再按示例调用：

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

标准输出每行只包含一条 JSON 响应，可用于管道处理。`Ctrl+D` 结束输入，`Ctrl+C` 中断退出。也可单独运行预设场景：

```bash
uv run python playground/kernel_playground.py hooks --amount 5
uv run python playground/kernel_playground.py context
uv run python playground/kernel_playground.py lifecycle
uv run python playground/kernel_playground.py lifecycle --fail-run
uv run python playground/kernel_playground.py validation
```

`hooks` 展示依赖排序、三种调用模式、嵌套调用与宿主独立状态；`context` 展示容器快照、跨空间事务、冲突和服务引用；`lifecycle` 打印阶段计划、实际回调与逆序清理，`--fail-run` 演示后台故障交付；`validation` 展示缺失依赖、依赖环和同优先级冲突在初始化之前失败。输出包含 ctx 版本、变更来源与字段，可修改脚本中的声明和优先级后重新运行。

声明、调用与生命周期的代码说明见仓库中的 `src/aurora_kernel/README.md`。

## 扩展 Bot 推理

默认认知执行器支持替换记忆召回、上下文装配和推理实现，也支持订阅步骤与工具执行前后的通知。插件通过普通 namespace hook 接入，放入 `extensions/plugins/` 后重启生效。扩展不会自动成为模型可用工具。

可先运行离线示例，对比默认实现与自定义 hook：

```bash
uv run python playground/react_playground.py
uv run python playground/react_playground.py --default
```

插件示例、回调约定与执行限制见仓库中的 `src/aurora_bot/engine/README.md`。替换整个认知执行策略仍通过 `CognitionRunner` 能力完成。
