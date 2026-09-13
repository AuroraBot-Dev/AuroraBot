"""提供 AuroraBot 的配置加载入口。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aurora.configs import load_config
    from aurora.contracts.config import AuroraConfig

__all__ = ["AuroraConfig", "load_config"]


def __getattr__(name: str) -> object:
    """惰性解析公共入口，避免 CLI 启动前导入运行时依赖。"""
    if name in {"AuroraConfig", "load_config"}:
        from aurora.configs import load_config
        from aurora.contracts.config import AuroraConfig

        return {"AuroraConfig": AuroraConfig, "load_config": load_config}[name]
    raise AttributeError(f"模块 {__name__!r} 没有属性 {name!r}")
