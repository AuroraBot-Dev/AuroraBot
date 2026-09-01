from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from aurora import load_config
from aurora.config import assemble_config
from aurora.configuration.platforms import PLATFORMS_CONFIG, PlatformConfig
from aurora.configuration.storage import STORAGE_CONFIG, StorageConfig

if TYPE_CHECKING:
    from pathlib import Path

_TEMPLATE_PORT = 8765
_TEMPLATE_SESSION_TTL = 604800

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
name = "ops"
description = "ops 与 Panel 数据"
path = "%DATA_ROOT%/ops/"

[[storage]]
name = "logs"
description = "轮转文件日志"
path = "%DATA_ROOT%/logs/"
"""


def _load_platforms(tmp_path: Path, content: str) -> tuple[PlatformConfig, ...]:
    config_directory = tmp_path / "config"
    config_directory.mkdir(exist_ok=True)
    (config_directory / "platforms.toml").write_text(content, encoding="utf-8")
    return assemble_config(tmp_path, (PLATFORMS_CONFIG,)).get(PLATFORMS_CONFIG)


def _load_storage(tmp_path: Path, content: str) -> StorageConfig:
    config_directory = tmp_path / "config"
    config_directory.mkdir(exist_ok=True)
    (config_directory / "storage.toml").write_text(content, encoding="utf-8")
    return assemble_config(tmp_path, (STORAGE_CONFIG,)).get(STORAGE_CONFIG)


def test_template_exports_typed_panel_platform_configuration(configured_project: Path) -> None:
    configuration = load_config(configured_project)
    platforms = configuration.get(PLATFORMS_CONFIG)
    panel = next(item for item in platforms if item.id == "builtin.panel")

    assert panel.enabled is False
    assert panel.settings("host") == "127.0.0.1"
    assert panel.settings("port") == _TEMPLATE_PORT
    assert panel.settings("frontend_url") == "http://localhost:8766"
    assert cast("tuple[str, ...]", panel.settings("allowed_origins"))[0] == "http://localhost:8764"
    assert panel.settings("open_browser") is False
    assert panel.settings("session_ttl_seconds") == _TEMPLATE_SESSION_TTL


def test_template_exports_typed_storage_paths(configured_project: Path) -> None:
    storage = load_config(configured_project).get(STORAGE_CONFIG)

    assert storage.resolve("DATA_ROOT") == "data"
    assert storage.resolve("world") == "data/world"
    assert storage.resolve("ops") == "data/ops"
    assert storage.resolve("logs") == "data/logs"
    assert [entry.name for entry in storage.entries] == ["DATA_ROOT", "world", "ops", "logs"]


def test_panel_platform_parses_config_dict(tmp_path: Path) -> None:
    platforms = _load_platforms(
        tmp_path,
        """\
[[platform]]
id = "builtin.panel"
enabled = true
logging = "INFO"

[platform.config]
host = "127.0.0.1"
port = 8765
frontend_url = "http://localhost:8766"
allowed_origins = ["http://localhost:8766", "http://127.0.0.1:8766"]
open_browser = false
session_ttl_seconds = 604800
""",
    )
    panel = next(item for item in platforms if item.id == "builtin.panel")

    assert panel.enabled is True
    assert panel.settings("port") == _TEMPLATE_PORT
    assert panel.settings("allowed_origins") == ("http://localhost:8766", "http://127.0.0.1:8766")


@pytest.mark.parametrize("path", ("/absolute", "../outside", "a/../../outside", "C:/outside"))
def test_storage_rejects_non_project_relative_directories(tmp_path: Path, path: str) -> None:
    content = _STORAGE.replace('path = "%DATA_ROOT%/ops/"', f'path = "{path}"')
    storage = _load_storage(tmp_path, content)

    with pytest.raises(ValueError, match="项目内相对目录"):
        storage.resolve("ops")


def test_storage_rejects_unknown_variable_reference(tmp_path: Path) -> None:
    content = _STORAGE.replace('path = "%DATA_ROOT%/ops/"', 'path = "%MISSING%/x"')
    storage = _load_storage(tmp_path, content)

    with pytest.raises(ValueError, match="未声明的变量"):
        storage.resolve("ops")


def test_storage_rejects_cyclic_variable_reference(tmp_path: Path) -> None:
    content = '[[storage]]\nname = "A"\npath = "%B%/a"\n\n[[storage]]\nname = "B"\npath = "%A%/b"\n'
    storage = _load_storage(tmp_path, content)

    with pytest.raises(ValueError, match="循环引用"):
        storage.resolve("A")
