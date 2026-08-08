"""配置加载与启动快照注册入口。

导入规则：该包从 ``src.contracts.configuration`` 导入 DTO 与校验工具；
所有包均可导入本包以获取当前配置快照。
"""

from __future__ import annotations

from src.config.loader import load_configuration
from src.config.registry import get, init

__all__ = [
    "get",
    "init",
    "load_configuration",
]
