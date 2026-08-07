"""进程启动时注册的不可变配置快照。"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from src.config.loader import load_configuration

if TYPE_CHECKING:
    from src.contracts.configuration import AuroraConfig


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    NOT_INITIALIZED = "Configuration not initialized - call config.init() at process startup"


_config: AuroraConfig | None = None


def init(root: str | None = None, profile: str | None = None) -> AuroraConfig:
    """加载并注册配置。必须在进程早期显式调用一次。

    若未提供 root，从当前工作目录或已注册配置推断。
    """
    from pathlib import Path

    global _config  # noqa: PLW0603

    resolved_root = Path(root) if root else (_config.root if _config else Path.cwd())
    _config = load_configuration(resolved_root, profile)
    return _config


def get() -> AuroraConfig:
    """获取当前已加载的配置实例。

    Raises:
        RuntimeError: 尚未调用 :func:`init`。
    """
    if _config is None:
        raise RuntimeError(_Msg.NOT_INITIALIZED)
    return _config
