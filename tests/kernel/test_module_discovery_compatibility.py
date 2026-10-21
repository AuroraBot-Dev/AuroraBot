"""不同发现源使用同一兼容门禁，不在不兼容时执行模组钩子。"""

from __future__ import annotations

import asyncio
from importlib.metadata import EntryPoint
from typing import TYPE_CHECKING

import pytest

from aurora_bot.kernel import BuiltinSource, DirectorySource, EntryPointSource, compose_managed, discovery
from tests.kernel.support import Settings as _Settings

if TYPE_CHECKING:
    from pathlib import Path

    from aurora_bot.kernel import DiscoverySource

_PLUGIN = '''"""携带兼容清单的真实 Python 模组。"""

from pathlib import Path
from aurora_bot.kernel import ModuleManifest, module


async def prepare(context):
    """只有兼容声明才允许执行准备阶段。"""
    Path({marker!r}).write_text("prepare", encoding="utf-8")


@module(name="plugin", provides=str, manifest=ModuleManifest("7.2", {api!r}), prepare=prepare)
def build(context):
    """构造阶段留下可核对的副作用。"""
    Path({marker!r}).write_text("construct", encoding="utf-8")
    return "selected"


MODULE = build
'''


def _source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, *, compatible: bool) -> DiscoverySource:
    """只替换安装元数据枚举；发现、导入和装配均走生产实现。"""
    marker = tmp_path / "executed.txt"
    text = _PLUGIN.format(marker=str(marker), api=">=1,<2" if compatible else ">=2,<3")
    package_name = f"compat_{kind}_{'current' if compatible else 'future'}"
    monkeypatch.syspath_prepend(str(tmp_path))
    if kind == "builtin":
        package = tmp_path / package_name
        feature = package / "feature"
        feature.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        (feature / "__init__.py").write_text("", encoding="utf-8")
        (feature / "module.py").write_text(text, encoding="utf-8")
        return BuiltinSource(package_name)
    if kind == "entrypoint":
        (tmp_path / f"{package_name}.py").write_text(text, encoding="utf-8")
        entry = EntryPoint(name=package_name, value=package_name, group="aurorabot_plugin")

        def entries(*, group: str) -> tuple[EntryPoint, ...]:
            """以真实 EntryPoint.load 导入本次提供的插件。"""
            assert group == "aurorabot_plugin"
            return (entry,)

        monkeypatch.setattr(discovery, "entry_points", entries)
        return EntryPointSource()
    directory = tmp_path / "plugins"
    directory.mkdir()
    if kind == "directory_package":
        directory = directory / package_name
        directory.mkdir()
        (directory / "module.py").write_text(text, encoding="utf-8")
        return DirectorySource(directory.parent)
    (directory / f"{package_name}.py").write_text(text, encoding="utf-8")
    return DirectorySource(directory)


@pytest.mark.parametrize("kind", ["builtin", "directory_file", "directory_package", "entrypoint"])
@pytest.mark.parametrize("compatible", [False, True])
def test_discovered_modules_share_api_gate_before_real_prepare_and_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, *, compatible: bool
) -> None:
    """同一清单在全部发现形式中被保留，拒绝时不会产生任何钩子副作用。"""
    source = _source(tmp_path, monkeypatch, kind, compatible=compatible)
    specs = tuple(source.discover())
    assert len(specs) == 1
    assert specs[0].manifest.version == "7.2"

    async def scenario() -> None:
        """用真实生命周期入口证明兼容检查先于文件写入。"""
        if not compatible:
            with pytest.raises(ValueError, match="不兼容"):
                await compose_managed(_Settings(), specs)
            assert not (tmp_path / "executed.txt").exists()
            return
        handle = await compose_managed(_Settings(), specs)
        try:
            assert handle.assembly.get(str) == "selected"
            assert handle.assembly.modules[0].manifest is specs[0].manifest
            assert (tmp_path / "executed.txt").read_text(encoding="utf-8") == "construct"
        finally:
            await handle.close()

    asyncio.run(scenario())
