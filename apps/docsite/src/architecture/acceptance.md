---
order: 6
---

# 质量与验收

本页列出开发检查与主要行为测试。

## 质量门禁

Python 3.12，使用 uv；Ruff 行宽 120、LF、双引号。公开 API 保留类型注解，值对象优先 frozen + slots dataclass。源码文件不超过 600 行，纯字段模型可例外。

Python 检查使用 `uv run aurora check --fix`，包含 Ruff、格式、Pyright 和完整测试。
覆盖率按需使用 `uv run aurora check --test --coverage`，CI 使用同一命令并设置 20% 总体下限。
测试按能力组织，优先保护认知循环、持久化一致性、幂等与失败恢复、权限和路径边界、凭据脱敏及记忆时间正确性。
20% 是最低门槛，不是删减目标；简单展示、字段转发和常量不要求逐项测试，不为覆盖率补充用例。
文档构建使用根目录 `pnpm build docsite`，前端完整检查使用 `pnpm check apps`。

测试按能力分目录，使用 importlib 模式；跨能力 fake 放在 `tests/support/`，通过 `tests.*` 导入。输入保持确定，外部模型、工具与 MCP 使用 fake；世界持久化使用临时 SQLite，训练和推理可使用实际 CPU 模型。测试不依赖网络或真实密钥。

## 主体与认知

| 验收行为                                                                   | 主要证据                                                                                   |
| -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Bot 自主设置目标、保存检查点、登记未来检查；重启后没有新输入仍可继续       | `tests/runtime/test_bot_lifecycle.py`、`tests/runtime/test_bot_clock.py`                   |
| 选中替代主体或时间服务后，公开命令、上下文和到期唤起共享同一个实际实例     | `tests/runtime/test_bot_port_selection.py`、`tests/runtime/test_runtime_port_selection.py` |
| 同一种 root/child 循环，普通工具配对、委派结果恢复、不可见能力在效果前拒绝 | `tests/engine/test_engine_runtime.py`、`tests/kernel/test_assembly.py`                     |
| 原始输入、最新完整交互、必要恢复状态和证据受到保护；工具定义也计入预算     | `tests/runtime/test_bot_lifecycle.py`、`tests/engine/test_context_evidence.py`             |
| 世界只追加，域序号和全局游标单调，历史状态与当前状态分离                   | `tests/runtime/test_bot_history.py`、`tests/runtime/test_bot_views.py`、WorldJournal 测试  |

## 两个学习模型

| 验收行为                                                                                                                  | 主要证据                                                                                                                 |
| ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| GRU 训练、序列依赖、数据时间边界与导出重载一致性                                                                          | `tests/rhythm/test_rhythm_learning.py`、`tests/rhythm/test_rhythm_dataset.py`                                            |
| 等待判断和推理机会都可恢复；时间到期和环境变化分别触发检查                                                                | `tests/runtime/test_cadence.py`、`tests/rhythm/test_rhythm_policy.py`、`tests/rhythm/test_rhythm_observations.py`        |
| TGN 梯度训练、图关系排序与导出重载一致性                                                                                  | `tests/memory/test_memory_learning.py`、`tests/memory/test_memory_tgn.py`                                                |
| 候选受获知时间和游标约束；新旧修订、必要证据与历史回放不泄漏未来反馈                                                      | `tests/memory/test_memory_visibility.py`、`tests/memory/test_memory_continuity.py`、`tests/memory/test_memory_replay.py` |
| TGN 投影周期保存和重启恢复，前缀不兼容或内容损坏时重建                                                                    | `tests/memory/test_memory_checkpoint_lifecycle.py`、`tests/memory/test_memory_checkpoint_persistence.py`                 |
| 规则/GRU 与规则/TGN 四种组合在同一主体闭环中独立替换，学习模型删除导出文件后按归档版本重启，兑现自定安排并承接 GRU 隐状态 | `tests/runtime/test_neural_bot_lifecycle.py`                                                                             |
| 训练输入、权重、参数和验证结果拥有同一份可读取来源                                                                        | `tests/ai/test_training_artifacts.py`、`tests/ai/test_training_provenance.py`                                            |

这些测试验证训练与恢复行为。真实任务的收益评估方法见[节律与记忆模型](./learning#如何判断是否有帮助)。

## 模组与资源

| 验收行为                                                                  | 主要证据                                                                                                                                                         |
| ------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 功能包只通过稳定契约调用兄弟能力，新增包不修改中心依赖白名单              | `tests/foundation/test_dependency_boundaries.py`、`tests/kernel/test_builtin_modules.py`                                                                         |
| 模组完整命名空间身份、发布版本和内核 API 兼容校验贯穿发现、解析及生命周期 | `tests/kernel/test_module_namespaces.py`、`tests/kernel/test_module_compatibility.py`、`tests/kernel/test_module_discovery_compatibility.py`                     |
| 模组清单固定归档；本地包支持相对导入与重新发现                            | `tests/kernel/test_module_manifest_resources.py`、`tests/kernel/test_module_manifest_runtime.py`、`tests/kernel/test_plugin_packages.py`                         |
| 资源定义、别名、动态提供者和实例统一寻址，历史版本固定世界截点            | `tests/resources/test_resource_catalog.py`、`tests/resources/test_resource_provider_plugin.py`、`tests/resources/test_instance_resources.py`                     |
| 同一领域操作定义生成终端入口和结构化工具，扩展无需修改消费者              | `tests/operations/test_operation_plugin.py`、`tests/resources/test_resource_commands.py`                                                                         |
| 请求与回执持久幂等；开始后效果未知的非幂等操作不盲目重放                  | `tests/operations/test_operation_requests.py`、`tests/operations/test_operation_receipts.py`、`tests/operations/test_operation_payloads.py`                      |
| 模型、提供方、Agent、Prompt 和工具的实际固定版本可跨重启读回              | `tests/ai/test_model_provenance.py`、`tests/engine/test_agent_provenance.py`、`tests/engine/test_tool_provenance.py`、`tests/resources/test_resource_content.py` |
| 原生资源身份与 SDK 路由分离，配置地址和远端模型名真实传至 SDK 边界        | `tests/ai/test_provider_routing.py`、`tests/ai/test_provider_config_routing.py`                                                                                  |

## 外围环境

Console 输入先提交世界，本地帮助、清屏和退出不产生额外观察；普通和无界面模式共用装配及关闭。MCP 使用 SDK 2.x 的连接与协商，分页目录完整冻结，未选中的提供方不建立默认连接，事件只追加世界。未知效果不降为失败，不自动重试；目录变化不热替换正在运行的节点。日志不包含 Prompt、工具正文或密钥。

对应测试位于 `tests/runtime/` 和 `tests/mcp/`，其中 Console 测试为 `tests/runtime/test_console.py`。
