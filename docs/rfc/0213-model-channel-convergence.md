# 0213：模型通道收敛与角色钩子

状态：已接受
日期：2026-08-07
来源：RFC 0212 的通道与协商收敛修订

## 问题

1. **responses 通道收益不足**：AuroraBot 的工具链续轮自行管理 continuation items，responses 的原生优势（reasoning 可见性、previous_response_id 续接）未被使用；而 chat_completions 对几乎所有 provider 兼容，litellm 的 responses 是模拟转换——双通道是净成本。
2. **能力协商过重**：`chat/stream/tools/reasoning/vision` 是模型基础能力，由 models.dev 自动派生；negotiate 却为它们写了特殊分支（native 模式检查、continuation 通道匹配、native_responses 合并、tools 单独检查）。
3. **角色预设缺载体**：预设角色只是通道别名，无法表达"每个角色特殊适配逻辑与能力侧重"。

## 决定

### 1. 统一 chat_completions 通道

- 删除 `channels/responses.py`（ResponsesChannel 与 responses 解析）；quality/multimodal 均走 ChatChannel。
- `negotiate` 删除：`response_mode == "native"` 检查、continuation 通道匹配、`native_responses` 能力合并。
- `ModelContinuation.channel` 恒为 `"chat_completions"`。

### 2. 能力协商简化

- `required_capabilities` 与 `tools` 检查合并为一次子集判断（`required ∪ {tools if request.tools} ⊆ capabilities`）；冷启动 models.dev 不可用时的 `uncertain_roles` 放宽保留。
- 保留：参数受控字段防覆盖（`_FORBIDDEN_PARAMETERS`）、retry/cancel 策略契约检查、结构化输出协商（`structured_output` / `json_text_fallback` 二选一）。
- 基础能力（chat/stream/tools/reasoning/vision）一律由 models.dev 派生，不再有特殊分支。

### 3. 角色钩子：能力基线 + 请求适配

`RoleHandler` 增加两个可选扩展点：

- `capability_baseline: ClassVar[frozenset[str]]`：角色的能力侧重声明（合并进该角色的能力集；`_capabilities_for` 返回 `caps | baseline`）。
- `adapt_request(request) -> request`：per-role 请求适配钩子（默认原样返回）。

预设角色声明：

| 角色 | capability_baseline | 适配 |
| --- | --- | --- |
| fast | `∅` | 无（低延迟由模型配置决定） |
| quality | `{"reasoning"}` | 钩子占位 |
| multimodal | `{"vision"}` | 钩子占位 |

## 结果

- 双通道收敛为单通道：模型调用语义唯一，litellm 兼容面最大化。
- negotiate 从 ~45 行降到 ~25 行：基础能力检查统一、特殊分支删除。
- 角色预设有了语义载体：能力侧重（baseline）与特殊适配（adapt_request）各归其位。

## 兼容性

- 外部契约不变：`ModelRequest`/`ModelResult`/`ModelProvider` 无改动；`ModelContinuation.channel` 值域收敛为 `chat_completions`（engine 无感知）。
- 配置不变（RFC 0212 已移除 endpoint）。
- 测试：test_ai.py 删除 responses 相关用例，新增 baseline/adapt_request 用例。
