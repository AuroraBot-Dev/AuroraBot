"""配置文件热重载：文件监听与订阅者通知。

监视 config/ 目录下的 TOML 文件变更，在检测到写入关闭后
重新加载完整配置快照并通过回调通知所有订阅者。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    ROOT_NOT_DIR = "ConfigFileWatcher root is not a directory: {root}"
    TOML_GLOB = "**/*.toml"


@dataclass(slots=True)
class ConfigFileWatcher:
    """基于轮询的配置文件变更检测器。

    扫描 root 下所有 ``*.toml`` 文件并记录修改时间；
    当 :meth:`poll` 检测到任何文件发生变更、新增或删除时，
    通知所有已注册的订阅者回调。
    """

    root: Path
    _mtime: dict[str, float] = field(default_factory=dict)
    _subscriptions: list[Callable[[], None]] = field(default_factory=list)

    def __post_init__(self) -> None:
        """初始化后立即校验根目录并捕获初始文件状态。"""
        if not self.root.is_dir():
            raise NotADirectoryError(_Msg.ROOT_NOT_DIR.format(root=self.root))
        self._mtime = self._snapshot_mtimes()

    def subscribe(self, callback: Callable[[], None]) -> None:
        """注册变更回调；每次 poll 检测到变更时触发。"""
        self._subscriptions.append(callback)

    def unsubscribe(self, callback: Callable[[], None]) -> None:
        """取消已注册的变更回调。"""
        self._subscriptions.remove(callback)

    def poll(self) -> bool:
        """扫描所有已知配置文件，返回是否有任何文件变更。

        将当前快照与上次记录比较；若发现变更则刷新内部状态并通知所有订阅者。
        """
        current = self._snapshot_mtimes()
        if current == self._mtime:
            return False
        self._mtime = current
        for callback in self._subscriptions:
            callback()
        return True

    def _snapshot_mtimes(self) -> dict[str, float]:
        """获取当前所有配置文件及其修改时间。

        返回以相对路径为键、mtime 浮点数为值的字典。
        """
        snapshot: dict[str, float] = {}
        for path in self.root.glob(_Msg.TOML_GLOB):
            try:
                snapshot[path.relative_to(self.root).as_posix()] = path.stat().st_mtime
            except OSError:
                continue
        return snapshot
