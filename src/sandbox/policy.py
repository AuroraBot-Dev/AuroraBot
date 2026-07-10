"""Sandbox 访问策略引擎。

白名单 + 黑名单访问控制,规则优先级：黑名单 > 白名单 > 默认拒绝。

作者: [Wende](https://github.com/dengweitian0-svg)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from src.config import Config
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.sandbox.settings import SandboxConfig

logger = get_logger("AccessPolicy")

SANDBOX_DIR = Config.SANDBOX_DIR


@dataclass(slots=True)
class AccessPolicySnapshot:
    """AccessPolicy 的不可变快照，用于单次执行期间保持配置一致性。"""

    whitelist_files: frozenset[str]
    whitelist_dirs: frozenset[str]
    whitelist_modules: frozenset[str]
    whitelist_builtins: frozenset[str]
    blacklist_files: frozenset[str]
    blacklist_dirs: frozenset[str]
    blacklist_modules: frozenset[str]
    blacklist_builtins: frozenset[str]

    @classmethod
    def from_policy(cls, policy: AccessPolicy) -> AccessPolicySnapshot:
        """从 AccessPolicy 创建不可变快照。"""
        cfg = policy.config
        return cls(
            whitelist_files=cfg.whitelist_files,
            whitelist_dirs=cfg.whitelist_dirs,
            whitelist_modules=cfg.whitelist_modules,
            whitelist_builtins=cfg.whitelist_builtins,
            blacklist_files=cfg.blacklist_files,
            blacklist_dirs=cfg.blacklist_dirs,
            blacklist_modules=cfg.blacklist_modules,
            blacklist_builtins=cfg.blacklist_builtins,
        )


class AccessPolicy:
    """白名单 + 黑名单访问控制引擎。

    规则优先级：黑名单 > 白名单 > 默认拒绝。
    """

    def __init__(self, config: SandboxConfig) -> None:
        self._config = config

    @property
    def config(self) -> SandboxConfig:
        """返回当前生效的配置对象。"""
        return self._config

    def update_config(self, config: SandboxConfig) -> None:
        """热加载时更新配置。"""
        self._config = config

    def can_import_module(self, module_name: str) -> bool:
        """检查是否允许 import 指定模块。前缀匹配：禁止 os 时 os.path 也被禁止。"""
        # 黑名单优先：前缀匹配
        for blocked in self._config.blacklist_modules:
            if module_name == blocked or module_name.startswith(blocked + "."):
                return False
        # 白名单：精确匹配或前缀匹配
        for allowed in self._config.whitelist_modules:
            if module_name == allowed or module_name.startswith(allowed + "."):
                return True
        # 默认拒绝
        return False

    def can_use_builtin(self, name: str) -> bool:
        """检查是否允许使用指定内置函数。黑名单优先。"""
        if name in self._config.blacklist_builtins:
            return False
        return name in self._config.whitelist_builtins

    @staticmethod
    def _normalize_path(path: Path) -> Path:
        """将路径标准化为绝对路径。相对路径基于 SANDBOX_DIR 解析。"""
        if path.is_absolute():
            return path.resolve()
        return (SANDBOX_DIR / path).resolve()

    def can_read_file(self, path: Path) -> bool:
        """检查是否允许读取指定文件。"""
        abs_path = self._normalize_path(path)
        path_str = str(abs_path)
        # 黑名单优先
        if any(Path(path_str).match(pattern) for pattern in self._config.blacklist_files):
            return False
        # 白名单
        return any(Path(path_str).match(pattern) for pattern in self._config.whitelist_files)

    def can_read_dir(self, path: Path) -> bool:
        """检查是否允许读取指定目录。"""
        abs_path = self._normalize_path(path)
        path_str = str(abs_path)
        if any(Path(path_str).match(pattern) for pattern in self._config.blacklist_dirs):
            return False
        return any(Path(path_str).match(pattern) for pattern in self._config.whitelist_dirs)

    def can_open_file(self, path: Path, mode: str) -> bool:
        """检查是否允许以指定模式打开文件。写模式仅限 sandbox 目录内。"""
        abs_path = self._normalize_path(path)
        # 写模式限制在 sandbox 目录内
        if any(c in mode for c in ("w", "a", "x")):
            try:
                abs_path.relative_to(SANDBOX_DIR)
            except ValueError:
                return False
        # 读模式检查文件白名单
        return self.can_read_file(path)

    def snapshot(self) -> AccessPolicySnapshot:
        """创建当前配置的不可变快照。"""
        return AccessPolicySnapshot.from_policy(self)
