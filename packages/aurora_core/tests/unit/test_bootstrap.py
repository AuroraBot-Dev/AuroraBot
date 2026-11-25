"""验证自举目录和资源分类接收规则。"""

import pytest
from aurora_core.bootstrap import REGISTRY_DIRECTORY, Receiver, bootstrap
from aurora_core.ids import Id
from aurora_core.registry import RegistryEntry


def test_bootstrap_directory_references_same_entries():
    registry = bootstrap()
    directory = registry.get(REGISTRY_DIRECTORY)
    assert isinstance(directory.target, Receiver)
    children = registry.view(register_to=REGISTRY_DIRECTORY)
    for child in children:
        assert registry.get(child.id) is child
        assert directory.target.rejection_reason(child) is None


@pytest.mark.parametrize("kind", ["resource", "assembly", "contract"])
def test_resource_registry_preserves_kind(kind):
    registry = bootstrap()
    target = Id("org.aurora.core:registries/resources")
    resource = RegistryEntry(Id("dev.example:resources/example"), kind, object(), "测试插件", register_to=target)
    receiver = registry.get(target).target
    assert isinstance(receiver, Receiver)
    assert receiver.rejection_reason(resource) is None
    registry.register(resource)
    assert registry.view(register_to=target)[0] is resource
    assert registry.get(resource.id).kind == kind
