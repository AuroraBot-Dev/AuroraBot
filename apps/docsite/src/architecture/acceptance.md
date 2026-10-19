---
order: 6
---

# 质量与验收

本页把现行能力和可核对的离线证据对应起来。通过测试证明实现行为，不代表学习模型在开放环境中的收益已经成立。

## 质量门禁

Python 3.12，使用 uv；Ruff 行宽 120、LF、双引号；公开 API 有类型注解，值对象优先 frozen + slots dataclass。源码文件不超过 600 行，纯字段模型可例外；不通过新增 lint ignore 掩盖核心复杂度。测试使用确定输入和 fake 外部模型、工具，无网络或真实密钥依赖；世界持久化使用临时 SQLite，训练和推理使用实际 CPU 模型。

提交前运行 `uv run aurora check --fix`，同时检查 Ruff、格式、Pyright、完整测试和覆盖率。仅修改文档时还应运行文档站的 `pnpm build`，确认 Markdown 与内部链接可构建。

## 主体与认知

| 验收行为 | 主要证据 |
| --- | --- |
| Bot 自主设置目标、保存检查点、登记未来检查；重启后没有新输入仍可继续 | `tests/test_bot_lifecycle.py`、`tests/test_bot_clock.py` |
| 选中替代主体或时间服务后，公开命令、上下文和到期唤起共享同一个实际实例 | `tests/test_bot_port_selection.py`、`tests/test_runtime_port_selection.py` |
| 同一种 root/child 循环，普通工具配对、委派结果恢复、不可见能力在效果前拒绝 | `tests/test_engine_runtime.py`、`tests/test_assembly.py` |
| 原始输入、最新完整交互、必要恢复状态和证据受到保护；工具定义也计入预算 | `tests/test_bot_lifecycle.py`、`tests/test_context_evidence.py` |
| 世界只追加，域序号和全局游标单调，历史状态与当前状态分离 | `tests/test_bot_history.py`、`tests/test_bot_views.py`、WorldJournal 测试 |

`aurora:tool/definition/delegate` 是注册表中的内建工具，返回的 `DelegationRequest` 由 engine 应用。领域消息只含四种角色，Provider 边界单独完成 `message → user` 映射。必要内容超限时在模型和行动效果前失败，不能以截断关键约束换取继续运行。

## 两个学习模型

| 验收行为 | 主要证据 |
| --- | --- |
| GRU 确实训练、损失变化、利用序列历史，独立较晚经历且结果获知边界参与验证，导出重载保持判断 | `tests/test_rhythm_learning.py`、`tests/test_rhythm_dataset.py` |
| 等待判断和推理机会都可恢复；时间到期和环境变化分别触发检查 | `tests/test_cadence.py`、`tests/test_rhythm_policy.py`、`tests/test_rhythm_observations.py` |
| TGN 确实计算图梯度并训练，历史关系影响排序，导出重载保持结果 | `tests/test_memory_learning.py`、`tests/test_memory_tgn.py` |
| 候选受获知时间和游标约束；新旧修订、必要证据与历史回放不泄漏未来反馈 | `tests/test_memory_visibility.py`、`tests/test_memory_continuity.py`、`tests/test_memory_replay.py` |
| TGN 投影周期保存和重启恢复，前缀不兼容或内容损坏时重建 | `tests/test_memory_checkpoint_lifecycle.py`、`tests/test_memory_checkpoint_persistence.py` |
| 规则/GRU 与规则/TGN 四种组合在同一主体闭环中独立替换，学习模型删除导出文件后按归档版本重启，兑现自定安排并承接 GRU 隐状态 | `tests/test_neural_bot_lifecycle.py` |
| 训练输入、权重、参数和验证结果拥有同一份可读取来源 | `tests/test_training_artifacts.py`、`tests/test_training_provenance.py` |

同一场景逐项覆盖以下组合：

| 节律 | 记忆 | 共同验证 |
| --- | --- | --- |
| 规则 | 规则 | 环境唤起、自主保存目标、无新输入重启、到期认知与必要证据 |
| GRU | 规则 | 相同闭环，另验证归档权重与循环隐状态承接 |
| 规则 | TGN | 相同闭环，另验证归档权重与图投影检查点恢复 |
| GRU | TGN | 相同闭环，两个学习模型同时恢复和工作 |

联合场景使用确定的 fake LLM 表达 Bot 选择，真实世界、内核、工具、GRU、TGN、内容存储和时钟完成其余链路。它证明协作与连续性，不能证明相对于基线的真实任务增益。曝光和自评不是自动正确标签；收益评估需要独立效用来源、严格时间划分和固定预算的比较。当前图索引随历史增长，不承诺恒定内存或无限运行规模。

## 模组与资源

| 验收行为 | 主要证据 |
| --- | --- |
| 功能包只通过稳定契约调用兄弟能力，新增包不修改中心依赖白名单 | `tests/test_dependency_boundaries.py`、`tests/test_builtin_modules.py` |
| 模组完整命名空间身份、发布版本和内核 API 兼容校验贯穿发现、解析及生命周期 | `tests/test_module_namespaces.py`、`tests/test_module_compatibility.py`、`tests/test_module_discovery_compatibility.py` |
| 模组清单固定归档；本地包支持相对导入与重新发现 | `tests/test_module_manifest_resources.py`、`tests/test_module_manifest_runtime.py`、`tests/test_plugin_packages.py` |
| 资源定义、别名、动态提供者和实例统一寻址，历史版本固定世界截点 | `tests/test_resource_catalog.py`、`tests/test_resource_provider_plugin.py`、`tests/test_instance_resources.py` |
| 同一领域操作定义生成终端入口和结构化工具，扩展无需修改消费者 | `tests/test_operation_plugin.py`、`tests/test_resource_commands.py` |
| 请求与回执持久幂等；开始后效果未知的非幂等操作不盲目重放 | `tests/test_operation_requests.py`、`tests/test_operation_receipts.py`、`tests/test_operation_payloads.py` |
| 模型、提供方、Agent、Prompt 和工具的实际固定版本可跨重启读回 | `tests/test_model_provenance.py`、`tests/test_agent_provenance.py`、`tests/test_tool_provenance.py`、`tests/test_resource_content.py` |
| 原生资源身份与 SDK 路由分离，配置地址和远端模型名真实传至 SDK 边界 | `tests/test_provider_routing.py`、`tests/test_provider_config_routing.py` |

## 外围环境

Console 输入先提交世界，本地帮助、清屏和退出不产生额外观察；普通和无界面模式共用装配及关闭。MCP 使用 SDK 2.x 的连接与协商，分页目录完整冻结，未选中的提供方不建立默认连接，事件只追加世界。未知效果不降为失败，不自动重试；目录变化不热替换正在运行的节点。日志不包含 Prompt、工具正文或密钥。

这些边界由 Console、runtime、MCP 和日志测试分别验证。当前不提供抢占、并行认知、通用沙箱或自动在线参数训练；新增能力需要独立用例与测试，不能仅由消息名或接口声明推断已经存在。
