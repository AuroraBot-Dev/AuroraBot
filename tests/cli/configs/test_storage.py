from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from aurora import load_config
from aurora.configs.storage import CONFIG_SPEC as STORAGE_CONFIG
from aurora.configurator import assemble_config
from aurorabot.world.config import StorageEntry, resolve_storage_directory

if TYPE_CHECKING:
    from pathlib import Path

_STORAGE = """\
[[storage]]
name = "DATA_ROOT"
description = "所有数据的根"
path = "data/"

[[storage]]
name = "world"
description = "世界日志库"
path = "%DATA_ROOT%/world/"

[[storage]]
name = "cache"
description = "临时缓存"
path = "%DATA_ROOT%/cache/"

[[storage]]
name = "logs"
description = "轮转文件日志"
path = "%DATA_ROOT%/logs/"
"""


def _load_storage(tmp_path: Path, content: str) -> tuple[StorageEntry, ...]:
    config_directory = tmp_path / "config"
    config_directory.mkdir(exist_ok=True)
    (config_directory / "storage.toml").write_text(content, encoding="utf-8")
    return assemble_config(tmp_path, (STORAGE_CONFIG,)).get(STORAGE_CONFIG).entries


def test_template_exports_typed_storage_paths(configured_project: Path) -> None:
    storage = load_config(configured_project).get(STORAGE_CONFIG).entries

    assert resolve_storage_directory(storage, "DATA_ROOT") == "data"
    assert resolve_storage_directory(storage, "world") == "data/world"
    assert resolve_storage_directory(storage, "logs") == "data/logs"
    assert [entry.name for entry in storage] == ["DATA_ROOT", "world", "logs"]


@pytest.mark.parametrize("path", ("/absolute", "../outside", "a/../../outside", "C:/outside"))
def test_storage_rejects_non_project_relative_directories(tmp_path: Path, path: str) -> None:
    content = _STORAGE.replace('path = "%DATA_ROOT%/cache/"', f'path = "{path}"')
    storage = _load_storage(tmp_path, content)

    with pytest.raises(ValueError, match="项目内相对目录"):
        resolve_storage_directory(storage, "cache")


def test_storage_rejects_unknown_variable_reference(tmp_path: Path) -> None:
    content = _STORAGE.replace('path = "%DATA_ROOT%/cache/"', 'path = "%MISSING%/x"')
    storage = _load_storage(tmp_path, content)

    with pytest.raises(ValueError, match="未声明的变量"):
        resolve_storage_directory(storage, "cache")


def test_storage_rejects_cyclic_variable_reference(tmp_path: Path) -> None:
    content = '[[storage]]\nname = "A"\npath = "%B%/a"\n\n[[storage]]\nname = "B"\npath = "%A%/b"\n'
    storage = _load_storage(tmp_path, content)

    with pytest.raises(ValueError, match="循环引用"):
        resolve_storage_directory(storage, "A")
