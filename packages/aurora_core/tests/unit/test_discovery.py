"""验证发现选择、依赖与整批登记。"""

from importlib.metadata import EntryPoint

import pytest
from aurora_core.bootstrap import bootstrap
from aurora_core.discovery import ENTRY_POINT_GROUP, Plugin, load_plugins, register_plugins
from aurora_core.ids import Id
from aurora_core.registry import RegistryEntry


def test_explicit_selection_precedes_broken_entry_point():
    plugin = Plugin("example")
    broken = EntryPoint(name="example", value="missing_module:factory", group=ENTRY_POINT_GROUP)
    assert load_plugins(explicit=[plugin], enabled=["example"], available=[broken]) == (plugin,)
    assert load_plugins(available=[broken]) == ()


def test_duplicate_missing_and_ambiguous_plugins():
    plugin = Plugin("example")
    with pytest.raises(ValueError, match="重复"):
        load_plugins(explicit=[plugin, plugin])
    with pytest.raises(ValueError, match="匹配数：0"):
        load_plugins(enabled=["example"], available=[])
    point = EntryPoint(name="example", value="unused:factory", group=ENTRY_POINT_GROUP)
    with pytest.raises(ValueError, match="匹配数：2"):
        load_plugins(enabled=["example"], available=[point, point])


def test_import_error_preserves_source_and_cause():
    point = EntryPoint(name="example", value="missing_module:factory", group=ENTRY_POINT_GROUP)
    with pytest.raises(RuntimeError, match="missing_module:factory") as error:
        load_plugins(enabled=["example"], available=[point])
    assert isinstance(error.value.__cause__, ModuleNotFoundError)


def test_required_plugins_must_be_selected():
    dependent = Plugin("dependent", requires=("base",))
    with pytest.raises(ValueError, match="base"):
        load_plugins(explicit=[dependent])
    assert len(load_plugins(explicit=[dependent, Plugin("base")])) == 2


def test_duplicate_definitions_leave_registry_unchanged():
    registry = bootstrap()
    before = registry.entries()
    entry = RegistryEntry(Id("dev.example:resources/test"), "resource", "内容", "example")
    with pytest.raises(ValueError, match="重复"):
        register_plugins(registry, [Plugin("one", (entry,)), Plugin("two", (entry,))])
    assert registry.entries() == before
