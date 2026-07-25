"""配置注册中心 — 模块级配置单例，支持热重载与订阅通知。"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from src.config.loader import load_configuration
from src.contracts.configuration import AuroraConfig


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    NOT_INITIALIZED = "Configuration not initialized - call config.init() at process startup"


ReloadCallback = Callable[[AuroraConfig], None]

_config: AuroraConfig | None = None
_subscribers: list[ReloadCallback] = []


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


def reload() -> AuroraConfig:
    """从同一起源重新加载全部 TOML 配置，通知所有订阅者。

    Raises:
        RuntimeError: 尚未调用 :func:`init`。
    """
    current = get()
    new_config = load_configuration(current.root, current.runtime.profile)
    global _config  # noqa: PLW0603
    _config = new_config
    for callback in _subscribers:
        callback(new_config)
    return new_config


def subscribe(callback: ReloadCallback) -> None:
    """注册 reload 回调，回调在每次成功 reload 后以新配置实例调用。"""
    _subscribers.append(callback)


def unsubscribe(callback: ReloadCallback) -> None:
    """取消已注册的 reload 回调。"""
    _subscribers.remove(callback)
