# 日志规范

本规范适用于 vNext。日志用于诊断运行时，不替代事件记录、效果回执或审计文件。

| 级别 | 用途 |
| --- | --- |
| `ERROR` | 不可恢复的节点、平台、存储或配置失败；应携带事件/效果标识。 |
| `WARNING` | 已降级、可恢复或被拒绝的操作。 |
| `INFO` | 运行时启动/停止、配置版本切换、平台连接状态和效果结果摘要。 |
| `DEBUG` | 单个事件处理、图路由、模型请求元数据、文件 I/O 与诊断细节。 |

规则：

- AMP 事件正文、SOUL 内容、用户内容、密钥和完整模型提示词默认不得写入 `INFO`。
- 每一条与事件或效果相关的日志应包含稳定的记录 ID；不得只依赖自由文本关联。
- `effect.requested`、`effect.succeeded` 与 `effect.failed` 的事实记录在 Kernel 工作区，不以日志作为唯一来源。
- 模型计费、调用参数和原生响应的记录规则由 RFC 0005 定义。
- vNext 代码统一通过 `src.utils.log_utils.get_logger()` 获取 logger；入口通过
  `configure_logging()` 应用 TOML 中的日志级别，不得另行调用 `logging.basicConfig()`。
- 日志使用稳定的 `key=value` 上下文。适用时至少包含 `cycle`、`record_id`、`episode_id`，并补充
  `node_id`、`model_role`、`capability`、`request_id`、`duration_ms`、`status` 或 `reason`。
- `INFO` 记录生命周期和结果摘要，`DEBUG` 记录调度细节；循环空转、inbox 扫描和状态文件写入不得在
  `INFO` 逐次刷屏。
- 不记录模型消息、continuation 内容、工具参数值或工具结果正文。允许记录消息数、工具数、参数键名、
  token 数、费用、结果状态和长度等不可还原的元数据。
- 捕获异常时，边界层负责记录一次日志。可恢复失败使用 `WARNING`，导致记录或 episode 进入错误状态的失败
  使用 `ERROR`；下层重新抛出时避免重复打印同一堆栈。
