"""AuroraBot 微内核与显式声明入口。"""

from .declarations import entry_from, operation, plug
from .ids import Id

__all__ = ["Id", "entry_from", "operation", "plug"]
