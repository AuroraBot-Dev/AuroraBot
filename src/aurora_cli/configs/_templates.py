"""配置项自带模板与配套资源；只补齐个人目录中缺失的文件。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from aurora_cli.utils.modules import discover_module_names

if TYPE_CHECKING:
    from collections.abc import Iterable

_DIRECTORY = Path(__file__).parent


def config_names() -> tuple[str, ...]:
    """按目录名排序发现配置项，不导入解析器或运行时依赖。"""
    return discover_module_names((str(_DIRECTORY),))


def config_relative_path(name: str) -> str:
    return f"config/{name}.toml"


def _templates(names: Iterable[str] | None) -> list[tuple[str, Path, str]]:
    registered = config_names()
    selected = registered if names is None else tuple(sorted(set(names)))
    unknown = set(selected) - set(registered)
    if unknown:
        raise ValueError(f"未知配置：{', '.join(sorted(unknown))}")
    result: list[tuple[str, Path, str]] = []
    for name in selected:
        directory = _DIRECTORY / name
        template = directory / f"{name}.toml"
        if not template.is_file():
            raise FileNotFoundError(f"未找到配置模板：{template}")
        result.append((name, template, config_relative_path(name)))
        resources = directory / "resources"
        for source in sorted(resources.rglob("*")):
            if source.is_file():
                relative = source.relative_to(resources).as_posix()
                result.append((name, source, f"config/{name}/{relative}"))
    return result


def _destination(project_root: Path, relative: str) -> Path:
    root = project_root.resolve()
    target = root / relative
    if not target.resolve().is_relative_to(root):
        raise ValueError(f"配置路径越出项目目录：{relative}")
    if (target.exists() or target.is_symlink()) and not target.is_file():
        raise ValueError(f"配置目标不是普通文件：{relative}")
    return target


def missing_config_files(project_root: Path, names: Iterable[str] | None = None) -> dict[str, list[str]]:
    """按配置项列出缺失的个人文件，不创建目录、不加载配置值。"""
    missing: dict[str, list[str]] = {}
    for name, _source, relative in _templates(names):
        if not _destination(project_root, relative).exists():
            missing.setdefault(name, []).append(relative)
    return missing


def initialize_configs(project_root: Path, names: Iterable[str] | None = None) -> tuple[str, ...]:
    """从 CLI 自带资源创建缺失文件；个人配置与提示词均不覆盖。"""
    files = [(source, relative, _destination(project_root, relative)) for _, source, relative in _templates(names)]
    created: list[str] = []
    for source, relative, target in files:
        if target.exists():
            continue
        content = source.read_bytes()
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as stream:
                stream.write(content)
        except FileExistsError:
            # 并发初始化不能覆盖另一进程刚创建的个人文件。
            continue
        created.append(relative)
    return tuple(created)
