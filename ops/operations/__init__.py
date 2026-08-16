"""操作体系：RESTful 资源树与命令文本同构的操作目录。

子模块按域组织，路径镜像 src 包层级：engine / memory / ai / agents / config / prompt /
extensions / apps，以及会话与输出（面板聊天语义）。各子模块被 ``ops.registry._load_all`` 显式导入。
"""
