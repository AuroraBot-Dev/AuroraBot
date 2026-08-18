# AuroraBot 演化路线

当前目标是持续验证 `AgentTree` 是否足以承载宏大构想。

## 现在：稳定最小语义

- [x] 一棵 AgentTree 表达一次完整运行；
- [x] system/message/assistant/tool 四角色上下文；
- [x] 节点级 profile、model、tools 和初始 message；
- [x] 普通工具往返与 delegate child 恢复；
- [x] 项目配置、组合根和离线端到端测试；
- [x] LiteLLM 模型网关、本地 Console 与 start 统一生命周期；
- [ ] 明确多 Tool call、child 失败和循环上界的黄金测试；
- [ ] 用至少两个不同 Model adapter 验证 model 端口没有泄漏供应商语义；
- [ ] 用至少两个真实 Tool 验证工具契约。

## 下一步：围绕树增加能力

每项能力独立验证，不预先建立通用扩展框架：

1. AgentTree 的显式导入/导出；
2. 环境事件如何转化为 message；
3. 长上下文如何在树内显式压缩；
4. 多棵树之间的主动节律；
5. 等价树语义下的并发调度；
6. 效果授权和不可撤回工具的提交边界。

## 工程化能力的门槛

只有核心语义经过真实使用后，才评估持久化、恢复、MCP、Panel、记忆、运维和发布。每项重建都必须回答：它修改了哪条
AgentTree 语义、为什么不能作为外部适配器、失败时留下什么树状态，以及如何用离线测试证明。
