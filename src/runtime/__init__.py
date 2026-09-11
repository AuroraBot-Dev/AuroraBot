"""Bot 进程门面与装配工厂。"""

from src.runtime.core import AuroraRuntime
from src.runtime.factory import create_runtime

__all__ = ["AuroraRuntime", "create_runtime"]
