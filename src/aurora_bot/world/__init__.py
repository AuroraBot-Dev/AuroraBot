"""Bot 世界提交存储实现。"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aurora_bot.world.store import SqlAlchemyWorldJournal

__all__ = ["SqlAlchemyWorldJournal"]

_EXPORTS = {"SqlAlchemyWorldJournal": "aurora_bot.world.store"}


def __getattr__(name: str) -> object:
    """惰性解析公共出口，避免仅导入存储配置就加载 SQLAlchemy。"""
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"模块 {__name__!r} 没有属性 {name!r}")
    return getattr(import_module(module_name), name)
