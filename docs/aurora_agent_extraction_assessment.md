# 执行包边界与独立性

核对日期：2026-11-09。control / agent 拆分和 AgentRuntime 解耦已经完成；原始评估与 harness 设想保存在[历史归档](archive/2026-11-09/aurora_agent_extraction_assessment.md)。

## 当前边界

| 包 | 拥有的能力 | 不应依赖 |
| --- | --- | --- |
| aurora_control | 执行身份、状态绑定、连接契约、四种控制组合 | agent、模型、bot、CLI、API |
| aurora_agent | ReAct、模型调用、工具执行、默认阶段、AgentRuntime | bot、CLI、API |
| aurora_bot | 默认状态地址、配置、资源、产品运行与交流入口 | 不复制 agent 执行或调度机制 |

control 和 agent 的定义分别属于 org.aurora.control 和 org.aurora.agent；由 bot 分配的消息、引导和运行地址属于 org.aurora.bot，通过状态绑定注入组件。adapter 基础包可提供模型契约，供应商 SDK 不因导入 agent 而必需。

每个 agent 的执行必须由一个运行所有者统一管理。组件调用结束与状态保留是两件事；资源关闭、历史裁剪、快照恢复策略由装配和宿主明确。

## 验证入口

[包边界测试](../tests/e2e/test_package_boundaries.py)在独立进程阻止导入上层包，验证 control 执行、agent 工具往返和恢复，以及不依赖 CLI/API 的默认 bot。所需小应用位于 [tests/fixtures/runtime_apps](../tests/fixtures/runtime_apps/)，不再作为用户示例发布。

包内单测与跨包集成覆盖组件、取消、持久化、输入预算和运行中引导。依赖或分发变更还需构建 wheel，并在干净环境验证独立安装；不能以工作区导入成功替代安装验收。命令见[开发指南](development.md)。

## 尚未实现

独立 aurora_harness 产品包未引入。它需要实际消费者明确配置、资源和交互责任后再设计。新的安装助手使用既有 bot / MCP 装配，目的为首次配置，不等同于独立 harness 的实现或承诺。
