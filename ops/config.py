"""只读访问已注册的个人配置。"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from threading import RLock
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class ConfigSourceRef:
    """ops 所需的最小配置来源描述。"""

    name: str
    relative_path: str


class ConfigAccess:
    """只访问已注册的个人 TOML；源码模板永远不在范围内。"""

    def __init__(self, project_root: Path, sources: tuple[ConfigSourceRef, ...]) -> None:
        self._project_root = project_root.resolve()
        config_root = self._project_root / "config"
        if config_root.is_symlink():
            raise ValueError("个人 config/ 不能是符号链接")
        self._config_root = config_root.resolve()
        template_root = (self._project_root / "config.example").resolve()
        if self._config_root == template_root or self._config_root.is_relative_to(template_root):
            raise ValueError("个人 config/ 不能指向源码模板")
        self._sources = {source.name: source for source in sources}
        if len(self._sources) != len(sources):
            raise ValueError("ops 配置来源名称不能重复")
        self._lock = RLock()
        for source in sources:
            self._path(source)

    def snapshot(self) -> dict[str, Any]:
        return {
            "sources": [
                {"name": source.name, "path": source.relative_path, "exists": self._path(source).is_file()}
                for source in self._sources.values()
            ],
            "read_only": True,
        }

    def read(self, name: str) -> dict[str, Any] | None:
        source = self._sources.get(name)
        if source is None:
            return None
        path = self._path(source)
        with self._lock, path.open("rb") as stream:
            values = tomllib.load(stream)
        return {"name": source.name, "path": source.relative_path, "values": values}

    def _path(self, source: ConfigSourceRef) -> Path:
        path = (self._project_root / source.relative_path).resolve()
        if not path.is_relative_to(self._config_root) or path.suffix != ".toml":
            raise ValueError(f"ops 只能访问个人 config/ 下的 TOML：{source.relative_path}")
        return path
