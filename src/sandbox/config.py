"""Sandbox 配置管理。

提供 SandboxConfig dataclass 和 YAML 配置加载。

作者: [Wende](https://github.com/dengweitian0-svg)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from src.sandbox.base import SandboxConfigError
from src.sandbox.paths import PROJECT_ROOT
from src.utils import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    SECTION_MUST_BE_DICT = "{section_name} 必须是 dict, 实际得到 {type_name}"
    MISSING_REQUIRED_KEY = "default.yaml 缺失必需的 key: {section_name}.{key}"
    TYPE_ERROR_LIST = "{section_name}.{key} 类型错误: 期望 list, 实际得到 {type_name}"
    PATH_NOT_ABSOLUTE = (
        "{section_name}.{key} 中的路径必须为绝对路径，禁止相对路径: {pattern!r}（可用 PROJECT_DIR 占位符）"
    )
    YAML_NOT_FOUND = "default.yaml 不存在: {path}"
    YAML_PARSE_ERROR = "YAML 解析错误: {error}"
    TOP_LEVEL_MUST_BE_DICT = "YAML 顶层结构必须是 dict, 实际得到 {type_name}"
    MISSING_TOP_KEY = "default.yaml 缺失必需的顶层 key: {key}"


logger = get_logger("SandboxConfig")

# 所有 YAML 顶层 section 必须包含的 key
_REQUIRED_TOP_KEYS = ("whitelist", "blacklist")
# 每个 section 内必须包含的 key
_REQUIRED_SECTION_KEYS = ("files", "dirs", "modules", "builtins")


def _load_section(raw: dict, section_name: str) -> dict[str, frozenset[str]]:
    """从原始 dict 加载一个 whitelist/blacklist section。

    Raises:
    SandboxConfigError
        section 缺失、类型错误、或内部 key 类型不匹配。
    """
    section = raw[section_name]
    if not isinstance(section, dict):
        raise SandboxConfigError(
            _Msg.SECTION_MUST_BE_DICT.format(section_name=section_name, type_name=type(section).__name__)
        )
    result: dict[str, frozenset[str]] = {}
    for key in _REQUIRED_SECTION_KEYS:
        if key not in section:
            raise SandboxConfigError(_Msg.MISSING_REQUIRED_KEY.format(section_name=section_name, key=key))
        value = section[key]
        if not isinstance(value, list):
            raise SandboxConfigError(
                _Msg.TYPE_ERROR_LIST.format(section_name=section_name, key=key, type_name=type(value).__name__)
            )
        result[key] = frozenset(str(item).replace("PROJECT_DIR", str(PROJECT_ROOT)) for item in value)
        if key in ("files", "dirs"):
            for pattern in result[key]:
                if not Path(pattern).is_absolute():
                    raise SandboxConfigError(
                        _Msg.PATH_NOT_ABSOLUTE.format(section_name=section_name, key=key, pattern=pattern)
                    )
    return result


@dataclass(slots=True)
class SandboxConfig:
    """沙箱访问控制配置。"""

    whitelist_files: frozenset[str]
    whitelist_dirs: frozenset[str]
    whitelist_modules: frozenset[str]
    whitelist_builtins: frozenset[str]
    blacklist_files: frozenset[str]
    blacklist_dirs: frozenset[str]
    blacklist_modules: frozenset[str]
    blacklist_builtins: frozenset[str]

    @classmethod
    def from_yaml(cls, path: Path) -> SandboxConfig:
        """从 YAML 配置文件加载。

        Raises:
        SandboxConfigError
            YAML 文件不存在、YAML 语法错误、缺失 key、或 key 类型不匹配。
        """
        if not path.exists():
            raise SandboxConfigError(_Msg.YAML_NOT_FOUND.format(path=path))

        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise SandboxConfigError(_Msg.YAML_PARSE_ERROR.format(error=e)) from e

        if not isinstance(raw, dict):
            raise SandboxConfigError(_Msg.TOP_LEVEL_MUST_BE_DICT.format(type_name=type(raw).__name__))

        for key in _REQUIRED_TOP_KEYS:
            if key not in raw:
                raise SandboxConfigError(_Msg.MISSING_TOP_KEY.format(key=key))

        wl = _load_section(raw, "whitelist")
        bl = _load_section(raw, "blacklist")

        return cls(
            whitelist_files=wl["files"],
            whitelist_dirs=wl["dirs"],
            whitelist_modules=wl["modules"],
            whitelist_builtins=wl["builtins"],
            blacklist_files=bl["files"],
            blacklist_dirs=bl["dirs"],
            blacklist_modules=bl["modules"],
            blacklist_builtins=bl["builtins"],
        )


class ConfigReloader:
    """YAML 配置热加载器。

    调用方主动触发重载检查，YAML 解析失败时保留上次有效配置。
    """

    def __init__(self, config_path: Path, callback: Callable[[SandboxConfig], None]) -> None:
        """初始化重载器，绑定 YAML 文件路径和配置变更回调函数。"""
        self._config_path = config_path
        self._callback = callback
        self._last_mtime: float = 0.0

    def check_and_reload(self) -> None:
        """主动检查配置文件是否修改，若修改则重新加载。

        此方法应由调用方在需要时主动调用（如收到 SIGHUP 信号、定时器触发等）。

        回调在同一调用线程中同步执行，因此 callback 内的多步更新
        （如同时更新 manager config 和 policy）是原子的，不会被中断。
        如果改为异步或多线程调用，需重新审视此保证。
        """
        try:
            mtime = self._config_path.stat().st_mtime
            if mtime <= self._last_mtime:
                return
            self._last_mtime = mtime
            new_config = SandboxConfig.from_yaml(self._config_path)
            self._callback(new_config)
            logger.info("配置热加载成功")
        except (SandboxConfigError, yaml.YAMLError) as e:
            logger.warning(f"YAML 配置解析失败，保留上次有效配置: {e}")
