# 0212：AI 包总分结构——预设角色与模型配置分离

状态：已接受
日期：2026-08-07
来源：ai 包（1660 行）整理执行决定
先决条件：RFC 0200（包边界）、RFC 0206（配置快照）

## 问题

ai 包是扁平结构（`gateway`/`execution`/`_channels`/`_parsing`/`models`/`providers`），存在三处错位：

1. **角色语义无代码载体**：`endpoint`（通道选择）在 `models.toml` 配置里，而"fast=低延迟决策、quality=复杂推理、multimodal=多模态"这些任务角色语义散落在配置与代码各处；新增一个角色需要理解 4 个文件。
2. **通道与解析横切**：`_channels.py` + `_parsing.py` 按"两个通道"组织，但每处都引用 gateway 内部状态（`_capabilities_for`/`_models`/`_normalize_output`），职责边界模糊。
3. **配置重点错位**：role 段的重点是 model 绑定（provider + model + 能力覆盖），通道选择不应是配置职责——它是代码语义。

## 决定

### 1. `src/ai/roles/` 子包：预设角色（分）

```
roles/
  __init__.py       # 预设注册表：role_id → RoleHandler 类；resolve() 校验
  base.py           # RoleHandler ABC：声明 endpoint（通道）与共享工具序列化
  chat.py           # ChatRole：chat_completions 通道（调用 + 解析 + fallback）
  responses.py      # ResponsesRole：responses 通道（调用 + 解析）
  fast.py           # FastRole = ChatRole（预设声明：低延迟快速决策）
  quality.py        # QualityRole = ResponsesRole（预设声明：复杂推理）
  multimodal.py     # MultimodalRole = ChatRole（预设声明：多模态输入）
```

- `RoleHandler.endpoint` 由代码声明（`chat_completions` / `responses`）；每个角色文件是预设声明 + 可扩展点。
- **配置中出现未预设的 role → 启动时报错**（预设之外不可用）。

### 2. endpoint 归代码（配置契约变更）

- `models.toml [models.roles.*]` 移除 `endpoint` 字段，只保留 `provider` + `model` + 可选 `capabilities` 覆盖。
- `ModelRoleConfig` 删除 `endpoint`；`negotiate`/`initialize` 的通道判断改读 `RoleHandler.endpoint`。
- 换模型只改配置；换通道语义需要改预设代码（这是有意的：通道是代码语义）。

### 3. 通道实现并入 roles

- `_channels.py`/`_parsing.py` 拆散删除：
  - chat 相关（`_complete_chat` + fallback + `chat_message`/`chat_tool_calls`/`chat_assistant_item`/`usage`/`is_structured_output_error`）→ `roles/chat.py`
  - responses 相关（`_execute_responses_channel` + `response_tool_calls`/`responses_usage`/`response_cost`）→ `roles/responses.py`
  - 共享（`provider_tools`/`json_item`/`parse_arguments`）→ `roles/base.py`
  - `invalid_output_result` → `gateway.py`（唯一使用者）
- `execution.py` 收敛为公共执行基础设施：`TaskManager`/`CostTracker`/`GatewayError`/`GenerationTask`；`ModelCaller` 的 chat 调用封装（凭据/流式/成本）并入 `roles/chat.py`。

### 4. gateway 总控（总）

保留：能力协商（`negotiate`）、初始化（models.dev 能力解析）、`_normalize_output`、成本预算、日志、冷启动。
路由：`complete(request)` → `handler = self._handlers[request.role]` → `handler.complete(self, request, role_config, negotiated)`。
删除：`use_model`/`_callers`（ModelCaller 依赖）。

## 结果

- "新增角色"的答案收敛：在 `roles/` 加一个预设文件（声明通道与能力）+ 配置绑定 model。
- gateway 是纯总控；通道/解析/调用细节全部下沉 roles。
- 配置职责纯净：role 段只描述 model 绑定。

## 兼容性

- 配置契约：`models.toml` 移除 `endpoint`（旧配置启动失败，需删除该字段）；`ModelRoleConfig` 删字段。
- 外部契约不变：`ModelRequest`/`ModelResult`/`ModelProvider` 无改动；engine 无感知。
- 测试：`test_ai.py` 按新结构重写角色相关用例。
