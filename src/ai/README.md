# LiteLLM 统一模型网关

基于 [LiteLLM](https://github.com/BerriAI/litellm) 的多角色、流式打断、费用追踪 LLM 网关。

## 快速开始

```python
from src.ai.gateway import gateway

gen = gateway.fast.acompletion(
    messages=[{"role": "user", "content": "你好"}],
    max_tokens=100,
)
response = await gen          # ModelResponse
text = gen.plain()            # str
print(gen.cost)               # float (USD)
```

## 角色与默认模型

| 角色         | 用途                           | 默认模型                        | 环境变量                       |
| ------------ | ------------------------------ | ------------------------------- | ------------------------------ |
| `fast`       | 简单对话 / 门控判定            | `openai/gpt-4o-mini`            | `LLM_GATEWAY_FAST_MODEL`       |
| `quality`    | 复杂推理 / 记忆压缩 / 动作规划 | `openai/gpt-4o`                 | `LLM_GATEWAY_QUALITY_MODEL`    |
| `multimodal` | 图片理解                       | `openai/gpt-4o`                 | `LLM_GATEWAY_MULTIMODAL_MODEL` |
| `embedding`  | 文本嵌入                       | `openai/text-embedding-3-small` | `LLM_GATEWAY_EMBEDDING_MODEL`  |

除 embedding 外，所有对话角色共享相同 API 接口。

## 架构

```
业务代码
  gateway.fast.acompletion(...)        gateway.embedding.aembedding(...)
       │                                        │
       ▼                                        ▼
  ┌─────────────────────────────────────────────────┐
  │              ModelGateway (统一入口)            │
  │  fast │ quality │ multimodal │ embedding        │
  │       │         │            │                  │
  │  ┌────▼─────────▼────────────▼──────────┐       │
  │  │         ModelCaller (调用器)         │       │
  │  │  · acompletion() — 内部强制流式      │       │
  │  │  · aembedding()                      │       │
  │  └──────────────┬───────────────────────┘       │
  │                 │                               │
  │  ┌──────────────▼───────────────────────┐       │
  │  │    TaskManager  ·  CostTracker       │       │
  │  │  create/abort    按角色/模型汇总     │       │
  │  └──────────────────────────────────────┘       │
  └──────────────────────┬──────────────────────────┘
                         │ LiteLLM
                         ▼
        OpenAI / Anthropic / DeepSeek / ...
```

LiteLLM 内置定价缺失时自动回退到 [models.dev](https://models.dev) 社区定价数据库。

## 模块职责

| 模块             | 职责                                                                                                     |
| ---------------- | -------------------------------------------------------------------------------------------------------- |
| `ModelGateway`   | 统一入口，持有角色-模型映射。提供 `use_model(role)`、`abort_task()`、`cost_summary()`、`export_config()` |
| `ModelCaller`    | 单角色调用封装。强制流式对话、自动记录费用，禁止调用方传入 `model` 参数                                  |
| `TaskManager`    | 管理 asyncio Task，分配唯一 `task_id`，支持单个/全部打断                                                 |
| `CostTracker`    | 按角色/模型分类统计每次调用详情，线程安全                                                                |
| `GenerationTask` | `await` 获得 ModelResponse，`.plain()` 提取文本，`.cost` 取费用，`.task_id` 可打断                       |
| `models`         | 从 models.dev 拉取模型定价，作为 litellm 内置定价缺失时的回退数据源                                      |
| `providers`      | 自定义供应商注册与模型解析，将 `<provider>/<model>` 转换为 litellm 原生调用并注入 api_base/api_key       |

## 核心设计

### 强制流式 + 对外非流式

所有对话模型底层 `stream=True`，内部消费全部 chunk 后用 `stream_chunk_builder` 重建为完整 `ModelResponse`。调用方只需 `await gen` 拿到最终结果，无需感知流式细节。好处：上层透明 + 打断止损。

### 打断机制

```python
from src.ai.gateway import gateway, CancelledWithPartialResponse

gen = gateway.quality.acompletion(messages=[...])
task_id = gen.task_id

# 中途打断
await asyncio.sleep(2)
gateway.abort_task(task_id)

try:
    response = await gen
except CancelledWithPartialResponse as e:
    print("部分内容:", e.partial_response)
    print("已消耗费用:", e.cost)
```

- `CancelledWithPartialResponse` 是 `asyncio.CancelledError` 的子类，携带部分响应和估算费用
- 打断后 HTTP 连接关闭，服务器停止生成，未生成的 token 不计费

### 费用追踪

自动计算并记录每次调用的 token 消耗和费用：

```python
summary = gateway.cost_summary()
# {
#     "total_cost": 0.0123,
#     "by_role": {"fast": {"count": 10, "cost": 0.001}, ...},
#     "by_model": {"openai/gpt-4o-mini": {"count": 10, "cost": 0.001}, ...},
#     "records": [...]
# }
```

费用计算基于 LiteLLM 内置定价表。若模型定价缺失（如新发布模型），
自动回退到 [models.dev](https://models.dev) 社区定价数据库：

```
litellm.completion_cost()
  ↓ 失败
models.dev get_pricing_by_id()
  ↓ 不可用
return $0.00（兜底，记录 warning）
```

三层降级确保即使新模型也能获得合理的费用估算。

### 配置导出

```python
gateway.export_config()
# {"fast": "openai/gpt-4o-mini", "quality": "openai/gpt-4o", ...}
```

## 环境变量

```ini
# fast 角色模型（默认: openai/gpt-4o-mini）
LLM_GATEWAY_FAST_MODEL=openai/gpt-4o-mini

# quality 角色模型（默认: openai/gpt-4o）
LLM_GATEWAY_QUALITY_MODEL=openai/gpt-4o

# multimodal 角色模型（默认: openai/gpt-4o）
LLM_GATEWAY_MULTIMODAL_MODEL=openai/gpt-4o

# embedding 角色模型（默认: openai/text-embedding-3-small）
LLM_GATEWAY_EMBEDDING_MODEL=openai/text-embedding-3-small

# LLM 请求超时秒数（默认: 120）
LLM_TIMEOUT=120

# 门控/记忆压缩等短时请求超时秒数（默认: 30）
LLM_GATE_TIMEOUT=30
```

**无需配置 `BASE_URL`**，LiteLLM 根据 `provider/model_name` 自动解析端点。使用默认模型只需配置 `OPENAI_API_KEY` 即可运行。

> 如需使用其他供应商的模型，参考下方「自定义供应商」章节。

## 自定义供应商（如硅基流动、DeepSeek 等兼容 API）

`providers.py` 支持将任意 OpenAI 兼容 API 注册为网关供应商，
使用 `<provider>/<model>` 格式的模型 ID，网关自动转换为 litellm 原生调用。

### 内置供应商

| 前缀          | 供应商   | API 地址                        | API Key 环境变量      |
| ------------- | -------- | ------------------------------- | --------------------- |
| `siliconflow` | 硅基流动 | `https://api.siliconflow.cn/v1` | `SILICONFLOW_API_KEY` |

### 使用方式

```ini
# .env — 将网关角色指向自定义供应商
LLM_GATEWAY_FAST_MODEL=siliconflow/deepseek-ai/DeepSeek-V3
LLM_GATEWAY_QUALITY_MODEL=siliconflow/deepseek-ai/DeepSeek-V3
LLM_GATEWAY_EMBEDDING_MODEL=siliconflow/BAAI/bge-m3
SILICONFLOW_API_KEY=sk-xxx
```

网关在初始化时自动调用 `setup_providers()` 注册所有内置供应商。
调用链路中 `siliconflow/DeepSeek-V3` 被解析为 `openai/DeepSeek-V3`
并自动注入 `api_base` 和 `api_key`。

### 添加自定义供应商

```python
from src.ai.providers import ProviderConfig, setup_providers

setup_providers(
    ProviderConfig(
        prefix="my-provider",
        litellm_provider="openai",
        api_base="https://my-api.example.com/v1",
        api_key_env="MY_API_KEY",
    )
)
```

## models.dev 定价回退

`models.py` 模块为网关提供社区驱动的定价回退，数据来源 [models.dev](https://models.dev/api.json)。

### 快速使用

```python
from src.ai.models import get_pricing_by_id

pricing = await get_pricing_by_id("openai/gpt-4o")
# => {"input": 2.50, "output": 10.00}  或  None
```

### 缓存策略

| 场景             | 行为                                |
| ---------------- | ----------------------------------- |
| 缓存有效（< 1h） | 直接命中内存，0 网络开销            |
| 缓存过期         | 重新拉取；拉取失败则降级用过期缓存  |
| 首次拉取网络不通 | 返回 `None`                         |
| 并发调用         | `asyncio.Lock` + 双重检查，只拉一次 |

### 集成点

网关的 `_safe_cost` / `_safe_cost_per_token` 在 litellm 定价失败时自动调用 `get_pricing_by_id`，
上层业务代码无需感知。

## 异常体系

| 异常                           | 说明                           | retryable      |
| ------------------------------ | ------------------------------ | -------------- |
| `GatewayError`                 | 统一网关异常基类               | 由实例属性决定 |
| `CancelledWithPartialResponse` | 打断后抛出，携带部分响应和费用 | —              |

异常分类规则：

| litellm 异常                                                                                                         | retryable |
| -------------------------------------------------------------------------------------------------------------------- | --------- |
| `Timeout` / `RateLimitError` / `APIConnectionError` / `ServiceUnavailableError` / `InternalServerError` / `APIError` | ✅        |
| `AuthenticationError` / `BadRequestError` / `UnsupportedParamsError`                                                 | ❌        |

## 项目内使用

| 调用方                                   | 角色      | 场景                       |
| ---------------------------------------- | --------- | -------------------------- |
| `Agent.think()`                          | `fast`    | Agent 通用 LLM 推理        |
| `Internalizer._internalize()`            | `quality` | 事件内化为第一人称体验     |
| `Externalizer._externalize()`            | `quality` | 意识流行动意图转工具调用   |
| `EpisodicMemory._refine_summary_async()` | `quality` | 情景记忆压缩摘要           |

## 注意事项

- 调用方**禁止**传入 `model` 参数，模型由角色统一指定，违者 `PermissionError`
- embedding 角色调用 `acompletion()` 会抛出 `ValueError`
- `GenerationTask.plain()` 在 `await` 前返回 `""`
- 所有 cost 计算有 try/except 兜底：litellm → models.dev → $0.00，不阻塞调用流程
