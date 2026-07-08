"""MCP 发现与 manifest 解析单元测试。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from yaml.scanner import ScannerError

from src.platform.mcp_kit.discovery import _build_spec, discover_mcp_servers
from src.platform.mcp_kit.manifest import read_mcp_manifest

if TYPE_CHECKING:
    from pathlib import Path


class TestReadMCPManifest:
    def test_nonexistent(self, tmp_path: Path) -> None:
        result = read_mcp_manifest(tmp_path / "nonexistent.yaml")
        assert result is None

    def test_non_mcp_manifest(self, tmp_path: Path) -> None:
        manifest = tmp_path / "manifest.yaml"
        manifest.write_text(
            yaml.dump(
                {
                    "package": "im.polaris.plain",
                    "name": "普通应用",
                }
            ),
            encoding="utf-8",
        )
        result = read_mcp_manifest(manifest)
        assert result is None

    def test_mcp_server(self, tmp_path: Path) -> None:
        manifest = tmp_path / "manifest.yaml"
        manifest.write_text(
            yaml.dump(
                {
                    "package": "im.polaris.test",
                    "name": "测试",
                    "type": "mcp-server",
                    "mcp": {
                        "transport": "stdio",
                        "entry": "mcp_server.py",
                        "command": ["uv", "run", "python"],
                    },
                }
            ),
            encoding="utf-8",
        )
        result = read_mcp_manifest(manifest)
        assert result is not None
        assert result.mcp_entry == "mcp_server.py"

    def test_malformed_yaml(self, tmp_path: Path) -> None:
        manifest = tmp_path / "manifest.yaml"
        manifest.write_text("not: valid: yaml: [", encoding="utf-8")
        with pytest.raises(ScannerError):
            read_mcp_manifest(manifest)


# ── Build spec ──


class TestBuildSpec:
    def test_disabled_app(self, tmp_path: Path) -> None:
        manifest = tmp_path / "manifest.yaml"
        manifest.write_text(
            yaml.dump(
                {
                    "package": "im.polaris.test",
                    "name": "测试应用",
                    "version": "1.0.0",
                    "type": "mcp-server",
                    "mcp": {"entry": "mcp_server.py"},
                }
            ),
            encoding="utf-8",
        )
        spec = _build_spec(tmp_path, manifest, {"enabled": False})
        assert spec is None

    def test_mcp_enabled(self, tmp_path: Path) -> None:
        manifest = tmp_path / "manifest.yaml"
        manifest.write_text(
            yaml.dump(
                {
                    "package": "im.polaris.test",
                    "name": "测试",
                    "version": "1.0.0",
                    "type": "mcp-server",
                    "mcp": {
                        "entry": "mcp_server.py",
                    },
                }
            ),
            encoding="utf-8",
        )
        spec = _build_spec(tmp_path, manifest, {"enabled": True, "mcp": {"enabled": True}})
        assert spec is not None
        assert spec.enabled is True
        assert spec.key == "im.polaris.test"


# ── Discover ──


class TestDiscoverMCP:
    def test_no_apps_dir(self, tmp_path: Path) -> None:
        specs = discover_mcp_servers(
            apps_dir=tmp_path / "nonexistent",
            config_path=tmp_path / "config.yml",
        )
        assert specs == []

    def test_no_manifests(self, tmp_path: Path) -> None:
        (tmp_path / "empty_app").mkdir(parents=True)
        specs = discover_mcp_servers(apps_dir=tmp_path, config_path=tmp_path / "config.yml")
        assert specs == []

    def test_discover_mcp_app(self, tmp_path: Path) -> None:
        app_dir = tmp_path / "aurora-app-test"
        app_dir.mkdir()
        manifest = app_dir / "manifest.yaml"
        manifest.write_text(
            yaml.dump(
                {
                    "package": "im.polaris.test",
                    "name": "测试应用",
                    "version": "0.1.0",
                    "type": "mcp-server",
                    "mcp": {"entry": "mcp_server.py", "transport": "stdio"},
                }
            ),
            encoding="utf-8",
        )

        config_dir = tmp_path / "apps"
        config_dir.mkdir()

        specs = discover_mcp_servers(apps_dir=tmp_path, config_path=config_dir / "config.yml")
        assert len(specs) == 1
        assert specs[0].key == "im.polaris.test"
        assert specs[0].transport == "stdio"
        assert specs[0].enabled is True

    def test_matches_builtin_app_by_package_with_flat_config(self, tmp_path: Path) -> None:
        app_dir = tmp_path / "aurora-app-test"
        app_dir.mkdir()
        manifest = app_dir / "manifest.yaml"
        manifest.write_text(
            yaml.dump(
                {
                    "package": "im.polaris.test",
                    "name": "测试应用",
                    "type": "mcp-server",
                    "mcp": {"entry": "mcp_server.py"},
                }
            ),
            encoding="utf-8",
        )
        config_path = tmp_path / "config.yml"
        config_path.write_text(
            yaml.dump(
                {
                    "apps": {
                        "test": {
                            "package": "im.polaris.test",
                            "enabled": True,
                            "transport": "stdio",
                            "command": ["python", "mcp_server.py"],
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        specs = discover_mcp_servers(apps_dir=tmp_path, config_path=config_path)

        assert len(specs) == 1
        assert specs[0].enabled is True
        assert specs[0].command == ["python", "mcp_server.py"]
