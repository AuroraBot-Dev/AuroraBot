"""持久化 Agent 运行时实现。

Kernel 负责事件、Task/Agent 状态、邮箱、Activity 调度和因果边界，不决定认知内容，也不直接执行平台效果。
具体运行时类从 :mod:`src.kernel.runtime` 导入。保持本模块轻量可确保共享契约不会间接初始化运行时。
"""
