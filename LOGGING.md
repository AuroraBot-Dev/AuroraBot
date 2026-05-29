# 日志规范

## 级别约定

| 级别        | 用途                         | 示例                                                                         |
| ----------- | ---------------------------- | ---------------------------------------------------------------------------- |
| **ERROR**   | 功能中断、异常抛出           | `logger.exception("LLM 调用失败")`、`logger.error("启动失败: %s", exc)`      |
| **WARNING** | 异常但可恢复、用户操作纠正   | `logger.warning("配置缺失，使用默认值")`、`logger.warning("应用 %s 已注册")` |
| **INFO**    | **仅关键生命周期事件**       | 启动/停止、应用注册/注销、用户可见的请求结果                                 |
| **DEBUG**   | 操作细节、中间步骤、调试数据 | 单次请求、内存读写、事件推送、耗时统计、缓存操作                             |

## INFO 的边界

INFO 是给运维/用户看的，回答"系统现在处于什么状态"。以下**不**属于 INFO：

- ❌ 单次请求/事件的处理（"收到消息"、"执行命令"、"已推送事件"）
- ❌ 内部缓存读写（"已添加进 L1 缓存"、"已读取记忆"）
- ❌ LLM 调用细节（"LLM 请求: role=fast model=..."）
- ❌ 耗时统计（"[动作规划] step=历史加载 耗时=0.01s"）
- ❌ JSON/结构数据 dump（可用命令列表、事件队列）

以上统一使用 **DEBUG**。

## 单例初始化日志

单例采用懒加载代理模式（参考 `gateway`、`memory_manager`、`app_host`）。
初始化日志在**首次访问时**输出一条 INFO，子组件初始化使用 DEBUG：

```python
# ✅ 正确：管理器级一条 INFO
logger.info("memory 已启动")

# ✅ 正确：子组件静默
logger.debug("L1 缓存已启动")
```

避免因模块导入副作用导致同一事件重复日志。

## 日志格式

- **控制台**：Rich 彩色输出（DEBUG 青色、INFO 绿色、WARNING 黄色、ERROR 红色），自动语法高亮异常栈
- **文件**：纯文本 `%(asctime)s [%(levelname)s] %(name)s | %(message)s`，存放于 `logs/aurora.log`

## 获取 Logger

```python
from src.utils.log_utils import get_logger

logger = get_logger("ModuleName")
```

每个模块使用独立的 logger 名称，便于按模块过滤日志。
