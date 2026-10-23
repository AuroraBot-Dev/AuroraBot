from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from aurora_cli.configurator import assemble_config
from aurora_cli.contracts.config import ConfigSpec

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("name", "path", "message"),
    [
        ("first", "second.toml", "配置重复注册"),
        ("second", "first.toml", "配置文件重复注册"),
    ],
)
def test_duplicate_declarations_fail_before_loading_any_config(
    tmp_path: Path, name: str, path: str, message: str
) -> None:
    reads: list[Path] = []

    def parse(source: Path) -> str:
        reads.append(source)
        return source.name

    specs = (ConfigSpec("first", "first.toml", parse=parse), ConfigSpec(name, path, parse=parse))
    with pytest.raises(ValueError, match=message):
        assemble_config(tmp_path, iter(specs))
    assert reads == []


def test_config_iterators_are_loaded_once_with_sources_preserved(tmp_path: Path) -> None:
    reads: list[Path] = []

    def parse(source: Path) -> str:
        reads.append(source)
        return source.name

    specs = (ConfigSpec("first", "first.toml", parse=parse), ConfigSpec("second", "second.toml", parse=parse))
    config = assemble_config(tmp_path, iter(specs))

    assert reads == [tmp_path / "first.toml", tmp_path / "second.toml"]
    assert tuple(config.get(spec) for spec in specs) == ("first.toml", "second.toml")
    assert tuple(source.relative_path for source in config.sources) == ("first.toml", "second.toml")
    assert config.project_root == tmp_path
