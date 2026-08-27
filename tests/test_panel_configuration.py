from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from aurora import load_config
from aurora.config import collect_config
from aurora.configuration import runtime as runtime_module
from aurora.configuration import storage as storage_module
from aurora.configuration.runtime import RUNTIME_CONFIG, PanelConfig
from aurora.configuration.storage import STORAGE_CONFIG, StorageConfig

if TYPE_CHECKING:
    from pathlib import Path

_RUNTIME = """\
[runtime]
profile = "prod"

[runtime.tree]
node_id = "root"
agent = "builtin.root"

[runtime.console]
enabled = true

[runtime.panel]
enabled = true
host = "127.0.0.1"
port = 8765
frontend_url = "http://localhost:8766"
allowed_origins = ["http://localhost:8766", "http://127.0.0.1:8766"]
open_browser = false
session_ttl_seconds = 604800
"""

_TEMPLATE_PORT = 8765
_TEMPLATE_SESSION_TTL = 604800

_STORAGE = """\
[storage]
data_root = "data"
engine = "engine"
ai = "ai"
memory = "memory"
world = "world"
ops = "ops"
"""


def _load_runtime(tmp_path: Path, content: str) -> PanelConfig:
    config_directory = tmp_path / "config"
    config_directory.mkdir(exist_ok=True)
    (config_directory / "runtime.toml").write_text(content, encoding="utf-8")
    return collect_config(tmp_path, (runtime_module.register,)).get(RUNTIME_CONFIG).panel


def _load_storage(tmp_path: Path, content: str) -> StorageConfig:
    config_directory = tmp_path / "config"
    config_directory.mkdir(exist_ok=True)
    (config_directory / "storage.toml").write_text(content, encoding="utf-8")
    return collect_config(tmp_path, (storage_module.register,)).get(STORAGE_CONFIG)


def test_template_exports_typed_frozen_panel_configuration(configured_project: Path) -> None:
    configuration = load_config(configured_project)
    panel = configuration.get(RUNTIME_CONFIG).panel

    assert isinstance(panel, PanelConfig)
    assert panel.enabled is False
    assert panel.host == "127.0.0.1"
    assert panel.port == _TEMPLATE_PORT
    assert panel.frontend_url == "http://localhost:8766"
    assert panel.allowed_origins[0] == "http://localhost:8764"
    assert panel.open_browser is False
    assert panel.session_ttl_seconds == _TEMPLATE_SESSION_TTL


def test_template_exports_typed_storage_paths(configured_project: Path) -> None:
    storage = load_config(configured_project).get(STORAGE_CONFIG)

    assert storage == StorageConfig("data", "world", "ops")


def test_panel_parses_exact_values(tmp_path: Path) -> None:
    panel = _load_runtime(tmp_path, _RUNTIME)

    assert panel == PanelConfig(
        enabled=True,
        host="127.0.0.1",
        port=8765,
        frontend_url="http://localhost:8766",
        allowed_origins=("http://localhost:8766", "http://127.0.0.1:8766"),
        open_browser=False,
        session_ttl_seconds=604800,
    )


@pytest.mark.parametrize("host", ("0.0.0.0", "::", "example.org"))
def test_panel_rejects_non_loopback_host(tmp_path: Path, host: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        _load_runtime(tmp_path, _RUNTIME.replace("127.0.0.1", host))


@pytest.mark.parametrize("port", ("0", "65536"))
def test_panel_rejects_out_of_range_port(tmp_path: Path, port: str) -> None:
    with pytest.raises(ValueError, match=r"1 到 65535|正整数"):
        _load_runtime(tmp_path, _RUNTIME.replace("port = 8765", f"port = {port}"))


@pytest.mark.parametrize(
    "origin",
    (
        "http://localhost:8766/path",
        "http://localhost:8766?x=1",
        "http://localhost:8766#fragment",
        "http://user:pass@localhost:8766",
        "ftp://localhost:8766",
    ),
)
def test_panel_rejects_unsafe_origins(tmp_path: Path, origin: str) -> None:
    with pytest.raises(ValueError, match=r"来源|路径|凭据"):
        _load_runtime(tmp_path, _RUNTIME.replace('"http://localhost:8766", ', f'"{origin}", '))


def test_panel_rejects_duplicate_origins(tmp_path: Path) -> None:
    content = _RUNTIME.replace(
        'allowed_origins = ["http://localhost:8766", "http://127.0.0.1:8766"]',
        'allowed_origins = ["http://localhost:8766", "http://localhost:8766"]',
    )
    with pytest.raises(ValueError, match="不得重复"):
        _load_runtime(tmp_path, content)


def test_panel_frontend_url_must_be_an_allowed_origin(tmp_path: Path) -> None:
    content = _RUNTIME.replace('frontend_url = "http://localhost:8766"', 'frontend_url = "http://localhost:9999"')
    with pytest.raises(ValueError, match="frontend_url"):
        _load_runtime(tmp_path, content)


def test_panel_open_browser_requires_frontend_url(tmp_path: Path) -> None:
    content = _RUNTIME.replace('frontend_url = "http://localhost:8766"\n', "").replace(
        "open_browser = false", "open_browser = true"
    )
    with pytest.raises(ValueError, match="frontend_url"):
        _load_runtime(tmp_path, content)


def test_panel_rejects_non_positive_session_ttl(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="正整数"):
        _load_runtime(tmp_path, _RUNTIME.replace("session_ttl_seconds = 604800", "session_ttl_seconds = 0"))


@pytest.mark.parametrize("path", ("/absolute", "../outside", "a/../../outside", "C:/outside"))
def test_storage_rejects_non_project_relative_directories(tmp_path: Path, path: str) -> None:
    with pytest.raises(ValueError, match="项目内相对目录"):
        _load_storage(tmp_path, _STORAGE.replace('ops = "ops"', f'ops = "{path}"'))


def test_storage_rejects_missing_ops_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ops"):
        _load_storage(tmp_path, _STORAGE.replace('ops = "ops"\n', ""))
