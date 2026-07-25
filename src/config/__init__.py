"""配置加载、注册与热重载 — 唯一配置入口包。

导入规则：该包从 ``src.contracts.configuration`` 导入 DTO 与校验工具；
所有包均可导入本包以获取当前配置快照或触发重载。
"""

from __future__ import annotations

from src.config.hot_reload import ConfigFileWatcher
from src.config.loader import load_configuration
from src.config.registry import get, init, reload, subscribe, unsubscribe
from src.config.validator import validate_config

__all__ = [
    "ConfigFileWatcher",
    "get",
    "init",
    "load_configuration",
    "reload",
    "subscribe",
    "unsubscribe",
    "validate_config",
]
