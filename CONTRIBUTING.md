# 参与 AuroraBot

当前阶段优先验证 AgentTree 的核心语义，而不是恢复功能数量。适合贡献的方向包括：

- AgentTree 与四角色消息的不变量和反例；
- 不同模型、工具和委派行为的最小实验；
- 配置到运行时的组合边界；
- 更清晰的架构说明与离线回归测试。

涉及公共语义时先更新唯一 RFC。实现应保持 `contracts ← prompt/ai ← engine ← aurora` 依赖方向；测试必须离线、确定，使用
fake Model/Tool。提交前运行 `uv run aurora check`。
