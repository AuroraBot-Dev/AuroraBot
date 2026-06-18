"""Sandbox 配置管理。

提供 SandboxConfig dataclass 和 YAML 配置加载。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import yaml

from src.brain.sandbox.base import SandboxConfigError
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from pathlib import Path

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
        raise SandboxConfigError(  # noqa: TRY003
            f"{section_name} 必须是 dict, 实际得到 {type(section).__name__}"
        )
    result: dict[str, frozenset[str]] = {}
    for key in _REQUIRED_SECTION_KEYS:
        if key not in section:
            raise SandboxConfigError(f"default.yaml 缺失必需的 key: {section_name}.{key}")  # noqa: TRY003
        value = section[key]
        if not isinstance(value, list):
            raise SandboxConfigError(  # noqa: TRY003
                f"{section_name}.{key} 类型错误: 期望 list, 实际得到 {type(value).__name__}"
            )
        result[key] = frozenset(str(item) for item in value)
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
            raise SandboxConfigError(f"default.yaml 不存在: {path}")  # noqa: TRY003

        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise SandboxConfigError(f"YAML 解析错误: {e}") from e  # noqa: TRY003

        if not isinstance(raw, dict):
            raise SandboxConfigError(  # noqa: TRY003
                f"YAML 顶层结构必须是 dict, 实际得到 {type(raw).__name__}"
            )

        for key in _REQUIRED_TOP_KEYS:
            if key not in raw:
                raise SandboxConfigError(f"default.yaml 缺失必需的顶层 key: {key}")  # noqa: TRY003

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
