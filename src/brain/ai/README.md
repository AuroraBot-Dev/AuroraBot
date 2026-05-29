# LiteLLM 统一模型网关设计文档

## 1. 概述

### 1.1 背景

在现代应用中，往往需要同时对接多个模型提供商（如 OpenAI、Anthropic、Cohere 等）的不同模型，用于文本生成、多模态理解和文本嵌入。直接管理各个提供商的 `base_url`、认证方式和调用细节将导致代码耦合度高、维护困难。

本网关基于 [LiteLLM](https://github.com/BerriAI/litellm) 构建，**彻底屏蔽 provider 底层差异**，只需通过 `provider/model_name` 格式指定模型即可完成调用。同时提供**按角色（快速/质量/多模态/嵌入）配置模型**的能力，使上层业务只需关注“用哪个角色”而无需关心具体实现。

### 1.2 核心特性

- ✅ **零 base_url 配置**：依靠 LiteLLM 内置的 100+ 提供商路由表，自动解析端点与认证。
- ✅ **角色驱动**：预定义四种角色（快速、质量、多模态、词嵌入），用户只需配置四个字符串。
- ✅ **统一调用接口**：所有模型通过 `gateway.use_model(role).acompletion(...)` 调用，下游无感知。
- ✅ **内部强制流式 + 外部非流式返回**：所有对话模型底层使用流式请求，既能支持打断止损，又对调用方暴露非流式一次性结果。
- ✅ **完善的打断与费用追踪**：可随时取消生成任务，精确计算打断任务的 token 消耗；所有调用记录按角色、模型分类汇总，实时查看总费用。
- ✅ **配置导出**：可随时获取当前各角色绑定的模型名，方便监控与动态调整。

---

## 2. 架构设计

### 2.1 整体结构

```
┌──────────────────────────────────────────┐
│              业务代码                     │
│   gateway.fast.acompletion(...)           │
│   gateway.embedding.aembedding(...)      │
└───────────────────┬──────────────────────┘
                    │
┌───────────────────▼──────────────────────┐
│            ModelGateway (统一入口)        │
│  ┌─────────┐ ┌─────────┐ ┌──────────┐   │
│  │  fast   │ │ quality │ │multimodal│... │
│  └────┬────┘ └────┬────┘ └────┬─────┘   │
│       │           │           │          │
│  ┌────▼───────────▼───────────▼─────┐    │
│  │        ModelCaller (调用器)       │    │
│  │   - acompletion(强制流式)        │    │
│  │   - aembedding                  │    │
│  └────────────┬────────────────────┘    │
│               │                          │
│  ┌────────────▼────────────────────┐    │
│  │      TaskManager (任务管理)      │    │
│  │   - create_task / abort         │    │
│  └─────────────────────────────────┘    │
│               │                          │
│  ┌────────────▼────────────────────┐    │
│  │      CostTracker (费用记录)      │    │
│  │   - 按角色/模型分类统计          │    │
│  └─────────────────────────────────┘    │
└───────────────────┬──────────────────────┘
                    │  LiteLLM
                    ▼
   ┌─────────────────────────────────┐
   │   OpenAI / Anthropic / Cohere   │
   │         ... 100+ providers       │
   └─────────────────────────────────┘
```

### 2.2 模块职责

| 模块             | 职责                                                                                                                                |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `ModelGateway`   | 统一入口，持有角色-模型映射、任务管理器和费用记录器；提供 `use_model(role)`、`abort_task`、`cost_summary`、`export_config` 等方法。 |
| `ModelCaller`    | 特定角色模型的调用封装，内部强制流式对话、提供嵌入方法，调用后自动记录费用。                                                        |
| `TaskManager`    | 管理异步任务（基于 `asyncio.Task`），分配唯一 `task_id`，支持单个或全部取消。                                                       |
| `CostTracker`    | 记录每次调用的详细信息，并提供按角色、模型的分类汇总。                                                                              |
| `GenerationTask` | 包装 `asyncio.Task`，可 `await` 得到最终响应，同时携带单次费用（`.cost`）和任务 ID（`.task_id`）。                                  |

---

## 3. 核心模块详解

### 3.1 模型配置与角色

用户初始化时只需指定四个字符串，格式均为 `provider/model_name`：

```python
gateway = ModelGateway(
    fast="openai/gpt-4o-mini",
    quality="anthropic/claude-3-opus-20240229",
    multimodal="openai/gpt-4o",
    embedding="openai/text-embedding-3-small"
)
```

角色常量定义：

- `fast`：快速轻量模型，适用于简单对话。
- `quality`：高质量模型，适用于复杂推理。
- `multimodal`：支持图片输入的多模态模型。
- `embedding`：文本嵌入模型。

### 3.2 统一调用

**文本/多模态对话**：所有对话角色（fast, quality, multimodal）使用相同接口：

```python
gen = gateway.fast.acompletion(
    messages=[{"role": "user", "content": "Hello"}],
    max_tokens=100,
    temperature=0.7
)
response = await gen
print(response.choices[0].message.content)
```

**嵌入**：

```python
emb = await gateway.embedding.aembedding("Hello world")
print(len(emb.data[0]["embedding"]))
```

**多模态输入**（符合 OpenAI Vision API 格式）：

```python
gen = gateway.multimodal.acompletion(
    messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": "描述图片"},
            {"type": "image_url", "image_url": {"url": "https://example.com/img.jpg"}}
        ]
    }]
)
response = await gen
```

### 3.3 内部强制流式 + 外部非流式

- `ModelCaller.acompletion` **强制设置 `stream=True` 并添加 `stream_options={"include_usage": True}`**。
- 内部消费所有流式 chunk，使用 `litellm.stream_chunk_builder` 重建为标准非流式 `ModelResponse`。
- 返回一个 `GenerationTask` 对象，调用方 `await` 时直接获得完整响应，无需感知流式细节。

**优点**：对上层完全透明，同时流式连接为打断止损提供了可能。

---

## 4. 打断机制与止损

### 4.1 原理

流式生成过程中，若客户端取消异步任务，底层 HTTP 连接会被关闭，API 服务器检测到连接断开后会立即停止 token 生成。已生成的 token 仍会计费，但未生成的部分不会产生费用，从而达到“及时止损”。

### 4.2 使用方法

```python
gen = gateway.quality.acompletion(...)
task_id = gen.task_id

# 一段时间后决定打断
await asyncio.sleep(2)
gateway.abort_task(task_id)

try:
    response = await gen
except CancelledWithPartialResponse as e:
    print("已打断，已生成部分内容：", e.partial_response)
    print("本次打断估算费用：", e.cost)
```

- `abort_task(task_id)` 会取消对应的 `asyncio.Task`。
- 内部捕获 `CancelledError`，构建部分响应并计算费用，抛出 `CancelledWithPartialResponse` 异常。
- 外部可选择性处理该异常，拿到已生成的部分内容和费用。

### 4.3 非流式打断的说明

非流式请求即使在客户端取消，API 通常已经完成了所有 token 生成并计费。因此本网关对话模型**强制启用流式**，以充分利用打断止损能力。

---

## 5. 费用记录与统计

### 5.1 记录内容

`CostTracker` 为每次调用（包括正常完成和被打断）记录以下字段：

| 字段                | 说明                                      |
| ------------------- | ----------------------------------------- |
| `task_id`           | 任务 ID（由外部填充）                     |
| `role`              | 角色（fast/quality/multimodal/embedding） |
| `model`             | 具体模型名（如 `openai/gpt-4o`）          |
| `type`              | 调用类型（completion / embedding）        |
| `status`            | 状态（completed / cancelled）             |
| `prompt_tokens`     | 输入 token 数                             |
| `completion_tokens` | 输出 token 数                             |
| `cost`              | 费用（美元）                              |

### 5.2 费用计算方法

**正常完成**：使用 `litellm.completion_cost(final_response)` 或 `litellm.embedding_cost(response)` 直接计算，基于完整 `usage`。

**打断任务**：

- 若已收到最后一个携带 `usage` 的 chunk，则用 `completion_cost` 精确计算。
- 若未收到，则使用 `litellm.cost_per_token(model, prompt_tokens, completion_tokens)` 估算，其中 `completion_tokens` 通过累计已生成文本长度 ÷ 4 估算（或使用 `tiktoken` 精确计算，推荐安装 `tiktoken`）。

### 5.3 查询接口

`gateway.cost_summary()` 返回如下结构：

```python
{
    "total_cost": 0.0123,
    "by_role": {
        "fast": {"count": 10, "cost": 0.001},
        "quality": {"count": 2, "cost": 0.010},
        "multimodal": {"count": 1, "cost": 0.001},
        "embedding": {"count": 5, "cost": 0.0003}
    },
    "by_model": {
        "openai/gpt-4o-mini": {"count": 10, "cost": 0.001},
        ...
    },
    "records": [ ... ]   # 完整调用明细
}
```

---

## 6. 配置导出

`gateway.export_config()` 返回当前各角色绑定的模型名，格式：

```python
{
    "fast": "openai/gpt-4o-mini",
    "quality": "anthropic/claude-3-opus-20240229",
    "multimodal": "openai/gpt-4o",
    "embedding": "openai/text-embedding-3-small"
}
```

可用于日志输出、监控面板展示或动态切换模型时的基准比对。

---

## 7. 使用示例

### 7.1 完整流程

```python
import asyncio
from unified_gateway import ModelGateway, CancelledWithPartialResponse

async def main():
    # 初始化网关
    gateway = ModelGateway(
        fast="openai/gpt-4o-mini",
        quality="anthropic/claude-3-opus-20240229",
        multimodal="openai/gpt-4o",
        embedding="openai/text-embedding-3-small"
    )

    # 快速对话
    gen = gateway.fast.acompletion(
        messages=[{"role": "user", "content": "法国首都是哪？"}],
        max_tokens=50
    )
    reply = await gen
    print(reply.choices[0].message.content)
    print("费用:", gen.cost)

    # 多模态（图片）
    gen_mm = gateway.multimodal.acompletion(
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "描述图片"},
                {"type": "image_url", "image_url": {"url": "https://example.com/cat.jpg"}}
            ]
        }]
    )
    reply_mm = await gen_mm

    # 嵌入
    emb = await gateway.embedding.aembedding(["文本1", "文本2"])

    # 打断示例
    gen_long = gateway.quality.acompletion(
        messages=[{"role": "user", "content": "写一篇5000字小说"}]
    )
    task_id = gen_long.task_id
    await asyncio.sleep(1.5)
    gateway.abort_task(task_id)
    try:
        await gen_long
    except CancelledWithPartialResponse as e:
        print("打断成功，部分内容:", e.partial_response.choices[0].message.content[:50] if e.partial_response else "无")
        print("本次打断费用:", e.cost)

    # 查看统计
    summary = gateway.cost_summary()
    print("总费用:", summary["total_cost"])
    print("按角色:", summary["by_role"])

if __name__ == "__main__":
    asyncio.run(main())
```

### 7.2 批量任务与统一管理

```python
tasks = []
for prompt in prompts:
    gen = gateway.fast.acompletion(messages=[{"role": "user", "content": prompt}])
    tasks.append(gen)

# 如果需要统一打断
gateway.abort_all()

results = []
for gen in tasks:
    try:
        results.append(await gen)
    except CancelledWithPartialResponse:
        pass
```

---

## 8. 部署与运行

### 8.1 环境要求

- Python 3.9+
- 安装依赖：`pip install litellm python-dotenv`
- 推荐安装 `tiktoken` 以获得更精确的打断任务 token 估算：`pip install tiktoken`

### 8.2 环境变量

创建 `.env` 文件，填写所需提供商的 API Key：

```ini
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
COHERE_API_KEY=...
```

**无需设置任何 `BASE_URL`**，LiteLLM 将自动选择默认端点。

### 8.3 启动

直接导入 `ModelGateway` 使用，无需独立服务器。也可包装为 FastAPI 服务对外提供 REST API（可参考初始对话中的 FastAPI 示例）。

---

## 9. 扩展与注意事项

- **动态切换模型**：修改初始化字符串或运行时替换 `gateway._callers` 字典中的模型即可。
- **自定义参数**：`acompletion` 和 `aembedding` 的 `**kwargs` 会直接透传给 `litellm`，支持 `temperature`、`top_p`、`stop` 等所有标准参数。
- **成本单位为美元**，若使用非美元计价的提供商，需结合 LiteLLM 的定价表自行换算。
- **大规模并发**：`TaskManager` 和 `CostTracker` 使用了 `asyncio.Lock` 保证线程安全，适用于异步高并发场景。
- **日志与监控**：内置 `logging`，建议结合项目日志系统记录每次调用的 task_id 和费用，便于追溯。

---

## 10. 总结

本网关通过 LiteLLM 的统一抽象，让开发者彻底摆脱 `base_url` 和提供商标识的管理负担，仅需四个字符串即可接入主流模型的文本、多模态和嵌入能力。同时创新的“内部强制流式+外部非流式”设计在保持调用简洁性的前提下，提供了完整的打断止损与费用追踪能力，尤其适合需要精确控制成本和响应时间的生产环境。
