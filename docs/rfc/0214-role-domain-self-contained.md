# 0214：角色域自洽——每个角色自包含实现

状态：已接受
日期：2026-08-07
来源：RFC 0212/0213 的结构再调整

## 问题

`channels/` 与 `roles/` 分层清晰，但**角色多样化改造成本高**：

- 场景：multimodal 任务需要接受模型音频输出——处理逻辑必须写在 multimodal 角色里，但共享的 `ChatChannel.complete` 是整体方法，角色覆写需要复制大量调用/解析代码。
- 共享通道基类把所有角色钉在同一实现上，违背"每个角色可以特殊适配"的初衷。

## 决定

### 1. 每个角色自包含实现（无共享通道类）

```
roles/
  __init__.py       # ROLE_PRESETS + resolve()
  base.py           # RoleHandler 契约 + 共享纯函数（工具序列化、chat 解析、调用封装）
  fast.py           # FastRole：完整实现（自己的 complete，调用 base 共享函数）
  quality.py        # QualityRole：完整实现 + baseline={"reasoning"}
  multimodal.py     # MultimodalRole：完整实现 + baseline={"vision"}
```

- **删除共享 `ChatChannel` 类**：每个角色文件包含自己的 `complete` 实现。
- 重复逻辑（消息组装、litellm 调用、响应解析、fallback）收敛为 `base.py` 的**纯函数**——角色文件内调用，不是继承。
- 角色多样化 = 直接改该角色文件里的 `complete`（如 multimodal 加音频输出参数与音频内容解析），其他角色与总控无感。

### 2. 总控不变

`gateway` 仍只依赖 `roles.resolve()` 与 `RoleHandler` 契约（`complete`/`capability_baseline`/`adapt_request`）。

## 结果

- 多模态音频等 per-role 改造只改 `roles/multimodal.py` 一个文件，无继承链牵连。
- 角色文件自包含、可独立演进；共享逻辑以函数形式复用，不牺牲自包含。

## 兼容性

- 对外契约不变（`ModelRequest`/`ModelResult`/`ModelProvider`/配置）。
- import 路径更新：`src.ai.channels.*` → `src.ai.roles.*`（内部引用，测试同步）。
