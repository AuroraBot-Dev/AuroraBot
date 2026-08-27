"""读取已注册配置，并安全修改少量显式开放的个人配置项。"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock
from typing import Any

import tomlkit


@dataclass(frozen=True, slots=True)
class ConfigSourceRef:
    """ops 所需的最小配置来源描述。"""

    name: str
    relative_path: str


class ConfigAccess:
    """只访问已注册的个人 TOML；源码模板永远不在可写范围内。"""

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
            "writable": {"apps": ["enabled"], "extensions": ["enabled"]},
        }

    def read(self, name: str) -> dict[str, Any] | None:
        source = self._sources.get(name)
        if source is None:
            return None
        path = self._path(source)
        with self._lock, path.open("rb") as stream:
            values = tomllib.load(stream)
        return {"name": source.name, "path": source.relative_path, "values": values}

    def set_app_enabled(self, package: str, *, enabled: bool) -> dict[str, Any]:
        return self._set_enabled("apps", "app", "package", package, enabled)

    def set_extension_enabled(self, extension_id: str, *, enabled: bool) -> dict[str, Any]:
        return self._set_enabled("extensions", "extension", "id", extension_id, enabled)

    def _set_enabled(
        self,
        source_name: str,
        table_name: str,
        identifier_name: str,
        identifier: str,
        enabled: bool,
    ) -> dict[str, Any]:
        source = self._sources.get(source_name)
        if source is None:
            raise KeyError(f"配置尚未注册：{source_name}")
        path = self._path(source)
        with self._lock:
            document = tomlkit.parse(path.read_text(encoding="utf-8"))
            entries = document.get(table_name)
            if not isinstance(entries, list):
                raise ValueError(f"{source.relative_path} 缺少 [[{table_name}]]")
            entry = next((item for item in entries if item.get(identifier_name) == identifier), None)
            if entry is None:
                raise KeyError(f"{table_name} 不存在：{identifier}")
            previous = bool(entry.get("enabled", False))
            entry["enabled"] = enabled
            rendered = tomlkit.dumps(document)
            tomlkit.parse(rendered)
            self._write(path, rendered)
        return {
            "source": source.name,
            identifier_name: identifier,
            "enabled": enabled,
            "changed": previous != enabled,
            "restart_required": previous != enabled,
        }

    def _path(self, source: ConfigSourceRef) -> Path:
        path = (self._project_root / source.relative_path).resolve()
        if not path.is_relative_to(self._config_root) or path.suffix != ".toml":
            raise ValueError(f"ops 只能访问个人 config/ 下的 TOML：{source.relative_path}")
        return path

    @staticmethod
    def _write(path: Path, rendered: str) -> None:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            temporary.chmod(path.stat().st_mode)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
