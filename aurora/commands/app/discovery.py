"""只读取项目元数据，为无安装清单的仓库提供候选值。"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.commands.app.models import Repository


@dataclass(frozen=True, slots=True)
class InstallSuggestions:
    """候选启动命令未经运行验证，必须交由用户选择和确认。"""

    package: str
    name: str
    version: str
    description: str
    commands: tuple[tuple[str, ...], ...]
    notes: tuple[str, ...]


def discover_install(checkout: Path, repository: Repository) -> InstallSuggestions:
    """检查根目录声明，不执行项目代码、脚本或依赖安装。"""
    commands: list[tuple[str, ...]] = []
    notes: list[str] = []
    python = _read_metadata(checkout / "pyproject.toml", notes)
    project = python.get("project", {})
    project = project if isinstance(project, dict) else {}
    scripts = project.get("scripts", {})
    if isinstance(scripts, dict):
        prefix = ("uv", "run", "--frozen") if (checkout / "uv.lock").is_file() else ("uv", "run")
        commands.extend((*prefix, key) for key, value in scripts.items() if _entry(key, value))
    node = _read_metadata(checkout / "package.json", notes)
    scripts = node.get("scripts", {})
    if isinstance(scripts, dict):
        commands.extend(("npm", "--silent", "run", key) for key, value in scripts.items() if _entry(key, value))
        if scripts:
            notes.append("Node.js 应用需按仓库说明准备依赖和构建产物。")
    segments = [re.sub(r"[^a-z0-9]+", "", part.lower()) or "app" for part in repository.full_name.split("/")]
    segments = [part if part[0].isalpha() else f"app{part}" for part in segments]
    return InstallSuggestions(
        ".".join(("local", *segments)),
        _text(project.get("name")) or _text(node.get("name")) or repository.full_name,
        _text(project.get("version")) or _text(node.get("version")) or "0.0.0",
        repository.description or _text(project.get("description")) or _text(node.get("description")) or "MCP 应用",
        tuple(commands),
        tuple(notes),
    )


def _read_metadata(path: Path, notes: list[str]) -> dict[str, object]:
    if path.is_symlink() or path.is_junction():
        notes.append(f"未读取 {path.name}：元数据文件不得使用链接。")
        return {}
    if not path.exists():
        return {}
    try:
        content = path.read_text(encoding="utf-8")
        result = tomllib.loads(content) if path.suffix == ".toml" else json.loads(content)
        if not isinstance(result, dict):
            raise ValueError("根节点必须是对象")
    except (OSError, ValueError) as error:
        notes.append(f"无法识别 {path.name}，可手动填写：{error}")
        return {}
    return result


def _entry(key: object, value: object) -> bool:
    return isinstance(key, str) and bool(key.strip()) and not key.startswith("-") and bool(_text(value))


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
