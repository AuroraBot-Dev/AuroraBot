"""已发现配置的统一目录；查看、加载和模板初始化共用同一份声明。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Any

from aurora_cli.configurator import assemble_config

if TYPE_CHECKING:
    from collections.abc import Iterable

    from aurora_cli.contracts.config import AuroraConfig, ConfigSpec
    from aurora_cli.contracts.plugin import ConfigContribution


def relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or PureWindowsPath(value).drive or "\\" in value or ".." in path.parts:
        raise ValueError(f"配置路径必须是项目内的相对路径：{value}")
    if str(path) == ".":
        raise ValueError(f"配置路径必须指向文件：{value}")
    return str(path)


def destination(root: Path, relative: str) -> Path:
    root = root.resolve()
    target = root / relative_path(relative)
    if not target.resolve().is_relative_to(root):
        raise ValueError(f"配置路径越出项目目录：{relative}")
    if (target.exists() or target.is_symlink()) and not target.is_file():
        raise ValueError(f"配置目标不是普通文件：{relative}")
    if any(parent.exists() and not parent.is_dir() for parent in target.parents):
        raise ValueError(f"配置目标的父路径不是目录：{relative}")
    return target


@dataclass(frozen=True, slots=True)
class ConfigCatalog:
    entries: tuple[ConfigContribution, ...]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(entry.spec.name for entry in self.entries)

    @property
    def specs(self) -> tuple[ConfigSpec[Any], ...]:
        return tuple(entry.spec for entry in self.entries)

    def spec(self, name: str) -> ConfigSpec[Any]:
        for entry in self.entries:
            if entry.spec.name == name:
                return entry.spec
        raise ValueError(f"未知配置：{name}")

    def path(self, root: Path, name: str) -> Path:
        return destination(root, self.spec(name).path)

    def load(self, root: Path) -> AuroraConfig:
        for spec in self.specs:
            self.path(root, spec.name)
        return assemble_config(root, self.specs)

    def _files(self, root: Path, names: Iterable[str] | None) -> tuple[tuple[str, Path, str, Path], ...]:
        selected = self.names if names is None else tuple(sorted(set(names)))
        unknown = set(selected) - set(self.names)
        if unknown:
            raise ValueError(f"未知配置：{', '.join(sorted(unknown))}")
        return tuple(
            (entry.spec.name, file.source, file.destination, destination(root, file.destination))
            for entry in self.entries
            if entry.spec.name in selected
            for file in entry.files
        )

    def missing(self, root: Path, names: Iterable[str] | None = None) -> dict[str, list[str]]:
        missing: dict[str, list[str]] = {}
        for name, _source, relative, target in self._files(root, names):
            if not target.exists():
                missing.setdefault(name, []).append(relative)
        return missing

    def initialize(self, root: Path, names: Iterable[str] | None = None) -> tuple[str, ...]:
        # 全部目标与源资源先检查完，再创建任何文件；已有个人文件不读取模板、不覆盖。
        pending = [
            (relative, target, source.read_bytes())
            for _name, source, relative, target in self._files(root, names)
            if not target.exists()
        ]
        created: list[str] = []
        for relative, target, content in pending:
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with target.open("xb") as stream:
                    stream.write(content)
            except FileExistsError:
                continue
            created.append(relative)
        return tuple(created)
