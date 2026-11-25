"""产品预设只生成声明，保留已有配置并要求显式应用宿主候选。"""

import tomllib
from io import StringIO

import pytest
from aurora_adapter.mcp import transports
from aurora_adapter.mcp.bot import ASSEMBLY
from aurora_adapter.mcp.preset import PLUGINS, initialize
from aurora_core.discovery import load_plugins


@pytest.mark.parametrize("world,api", [(False, False), (True, False), (False, True), (True, True)])
def test_preset_is_explicit_idempotent_and_does_not_start_resources(tmp_path, monkeypatch, world, api):
    def forbidden(*args, **kwargs):
        pytest.fail("预设生成不应创建运行资源")

    monkeypatch.setattr(transports, "open_client", forbidden)
    assert initialize(tmp_path, world=world, api=api, output=StringIO()) == 0
    paths = {path: path.read_bytes() for path in tmp_path.rglob("*.toml")}
    host = tomllib.loads((tmp_path / "config/host.toml").read_text(encoding="utf-8"))
    assert host["assembly"] == str(ASSEMBLY)
    assert host["plugins"][: len(PLUGINS)] == list(PLUGINS)
    assert ("aurora_adapter.mcp.world" in host["plugins"]) is world
    assert ("aurora_api" in host["plugins"]) is api
    assert initialize(tmp_path, world=world, api=api, output=StringIO()) == 0
    assert {path: path.read_bytes() for path in tmp_path.rglob("*.toml")} == paths


def test_existing_host_and_user_templates_are_preserved(tmp_path):
    directory = tmp_path / "config"
    directory.mkdir()
    host = directory / "host.toml"
    original = '# 用户选择\nplugins=["aurora_config"]\n'
    host.write_text(original, encoding="utf-8")
    target = directory / "org.aurora.adapter/mcp.toml"
    target.parent.mkdir()
    target.write_text("# 未迁移的原始内容\n", encoding="utf-8")
    output = StringIO()
    assert initialize(tmp_path, output=output) == 2
    assert host.read_text(encoding="utf-8") == original
    assert target.read_text(encoding="utf-8") == "# 未迁移的原始内容\n"
    candidate = directory / "host.mcp.toml"
    values = tomllib.loads(candidate.read_text(encoding="utf-8"))
    assert values["plugins"].count("aurora_config") == 1
    assert values["assembly"] == str(ASSEMBLY)
    assert "--- host.toml" in output.getvalue() and "+++ host.mcp.toml" in output.getvalue()
    assert initialize(tmp_path, output=StringIO()) == 2
    candidate.write_text("# 另一个候选\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="内容不同"):
        initialize(tmp_path, output=StringIO())
    assert candidate.read_text(encoding="utf-8") == "# 另一个候选\n"
    assert host.read_text(encoding="utf-8") == original


def test_invalid_host_fails_before_writing_templates(tmp_path):
    directory = tmp_path / "config"
    directory.mkdir()
    host = directory / "host.toml"
    host.write_text("plugins=42\n", encoding="utf-8")
    with pytest.raises(ValueError):
        initialize(tmp_path, output=StringIO())
    assert list(directory.iterdir()) == [host]


def test_product_plugin_does_not_implicitly_enable_dependencies():
    with pytest.raises(ValueError, match="依赖"):
        load_plugins(enabled=["aurora_adapter.mcp.bot"])
