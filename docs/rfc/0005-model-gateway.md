# RFC 0005：模型网关

状态：草案
日期：2026-07-11

## 目标

`src/ai` 是所有模型调用的统一入口，不限于文本 LLM。它管理模型角色、Provider 路由、能力协商、调用中断、节流、参数传递、使用量和计费。

## 已确认决策

- 节点请求角色而不是硬编码模型，例如 `fast`、`quality`、`multimodal`、`embedding`，未来可加入 `tts` 等角色。
- 节点提交声明式 `ModelRequest`：输入、所需能力、预算、取消策略和响应模式；不得直接持有 Provider client。
- 网关必须在调用前协商能力。典型能力包括 tools、结构化输出、流式、视觉、embedding 和 provider-native Responses API。
- 支持两种响应模式：`normalized` 用于可移植节点；`native` 用于确实需要厂商原生端点或对象的节点。持久化记录必须是可序列化的规范 JSON，不得把 Python 原生响应对象写入工作区。
- Tool 定义与 tool call 结果必须拥有统一中间表示；Provider 专有字段只能经显式 native 通道使用。

## 待定

- `ModelRequest`、能力描述和原生响应包装的精确 schema。
- 多 Provider 失败回退、缓存、重试、并发和计费归属。
- 模型调用产生的效果与 Kernel/Platform 事件间的详细映射。

## 验收方向

同一节点在声明 `normalized + tools` 时能够跨兼容 Provider 工作；声明 `native Responses API` 时，网关要么提供该模式，要么在调用前给出明确、可诊断的拒绝。
