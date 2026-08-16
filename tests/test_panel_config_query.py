"""面板配置查询：extensions/apps 的 TOML 安全读写。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

from ops.runtime import PanelConfigQuery
from src.contracts import ExtensionFace

if TYPE_CHECKING:
    from pathlib import Path


def _query(tmp_path: Path) -> PanelConfigQuery:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "extensions.toml").write_text(
        """# 内建扩展
[[extension]]
id = "aurora.builtin.control"
version = "1.0"
enabled = true
factory = "aurora.builtin.control"
faces = ["control_action"]
capabilities = []
""",
        encoding="utf-8",
    )
    (config_dir / "apps.toml").write_text(
        """# MCP 应用
[[app]]
package = "org.aurora.clock"
enabled = false
transport = "stdio"
working_dir = "src/apps/aurora-app-clock"
command = ["uv", "run", "python", "mcp_server.py"]
env = []
timeout_seconds = 30
""",
        encoding="utf-8",
    )
    configuration = SimpleNamespace(
        root=tmp_path,
        extensions=(
            SimpleNamespace(
                id="aurora.builtin.control",
                version="1.0",
                enabled=True,
                factory="aurora.builtin.control",
                faces=frozenset({ExtensionFace.CONTROL_ACTION}),
                capabilities=frozenset(),
            ),
        ),
    )
    return PanelConfigQuery(configuration, None)  # type: ignore[arg-type]


def test_extension_and_app_lists_include_disabled(tmp_path: Path) -> None:
    query = _query(tmp_path)

    extensions = query.extensions()
    assert extensions[0]["id"] == "aurora.builtin.control"
    assert extensions[0]["enabled"] is True

    apps = query.apps()
    assert apps[0]["package"] == "org.aurora.clock"
    assert apps[0]["enabled"] is False


def test_toggle_extension_and_app_preserves_toml_comments(tmp_path: Path) -> None:
    query = _query(tmp_path)

    extension_result = query.set_extension_enabled("aurora.builtin.control", enabled=False)
    assert extension_result == {
        "id": "aurora.builtin.control",
        "enabled": False,
        "requires_restart": True,
    }
    extensions_text = (tmp_path / "config" / "extensions.toml").read_text(encoding="utf-8")
    assert "# 内建扩展" in extensions_text
    assert "enabled = false" in extensions_text

    app_result = query.set_app_enabled("org.aurora.clock", enabled=True)
    assert app_result == {
        "package": "org.aurora.clock",
        "enabled": True,
        "requires_restart": True,
    }
    apps_text = (tmp_path / "config" / "apps.toml").read_text(encoding="utf-8")
    assert "# MCP 应用" in apps_text
    assert "enabled = true" in apps_text


def test_toggle_missing_entries_raise_key_error(tmp_path: Path) -> None:
    query = _query(tmp_path)

    try:
        query.set_extension_enabled("missing", enabled=True)
    except KeyError as error:
        assert "missing" in str(error)
    else:
        raise AssertionError("missing extension should raise KeyError")

    try:
        query.set_app_enabled("missing", enabled=True)
    except KeyError as error:
        assert "missing" in str(error)
    else:
        raise AssertionError("missing app should raise KeyError")
