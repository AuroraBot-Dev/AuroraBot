# Cognitive Kernel Beta

AuroraBot 的新内核位于 `src/kernel/`。它以 `data/kernel/` 为可审计工作区，以 SQLite 元数据和内容寻址对象保存不可变认知事件。

## 事件与能力

外部事件经 MCP bridge、控制台或 `data/kernel/inbox/external/*.json` 进入 `input.external`。感知、注意力、路由、快速反应、复杂规划、审查、发布、效果反馈、反思和上下文帧都是独立节点。

`src.ai.gateway` 是模型 capability adapter：节点提交 `capability.model.request` 并指定 `model_role`（`fast`、`quality` 或 `multimodal`）；Gateway 节点只选择/执行模型并返回结果。注意力门控、规划、审查与反思是独立认知节点，不能由 Gateway 自行决定。

复杂规划默认可产生 `capability.mcp.request`，由 MCP capability 通过 `MCPClientManager.call_tool()` 执行。记忆访问经现有 `UnifiedMemoryManager` 适配，输出先到 `output.candidate`，审查通过后才成为 `output.published`。

## 节律与可视化

运行时持续产生 `system.tick`；`builtin.rhythm` 会根据 tick 调度低优先级 dream 请求。所有循环沿 `causation_id` 传播并受 `max_hops` 限制。

```powershell
uv run python bot.py
```

向 `data/kernel/inbox/external/` 投递 UTF-8 JSON，例如：

```json
{"source":"filesystem","session_id":"demo","payload":{"summary":"环境温度变化","temperature":22}}
```

生产者应先写入临时文件，再原子改名为 `.json` 文件。
