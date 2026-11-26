"""验证来源声明的结构、身份约束与显式插件依赖。"""

from typing import cast

import pytest
from aurora_core.discovery import load_plugins
from aurora_world.configuration import SOURCE_CONFIG


@pytest.mark.parametrize(
    "value",
    [
        {"unknown": True},
        {"sources": [{}]},
        {"sources": [{"source": "invalid", "source_id": "a"}]},
        {"sources": [{"source": "dev.test:sources/a", "source_id": " "}]},
        {"sources": [{"source": "dev.test:sources/a", "source_id": "a", "config": []}]},
        {"sources": [{"source": "dev.test:sources/a", "source_id": "a"}] * 2},
    ],
)
def test_invalid_declarations_are_rejected(value):
    with pytest.raises(ValueError):
        SOURCE_CONFIG.parse(value)


def test_defaults_are_copied_without_changing_input():
    assert cast(dict, SOURCE_CONFIG.parse({}))["sources"] == []
    value = {"sources": [{"source": "dev.test:sources/a", "source_id": "a"}]}
    assert cast(dict, SOURCE_CONFIG.parse(value))["sources"] == [{**value["sources"][0], "config": {}}]
    assert "config" not in value["sources"][0]


def test_configuration_plugin_requires_explicit_dependencies():
    with pytest.raises(ValueError):
        load_plugins(enabled=["aurora_world.configuration"])
    plugins = load_plugins(enabled=["aurora_world", "aurora_config", "aurora_world.configuration"])
    assert {item.name for item in plugins} == {"aurora_world", "aurora_config", "aurora_world.configuration"}
