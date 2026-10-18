"""资源定义先于处理者公开，查询目录的操作不制造构造依赖环。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from src.contracts.operation import OPERATION_CONTRIBUTIONS, OperationDefinition
from src.contracts.pkgs.resources import ResourceCatalog
from src.contracts.resource import ResourceDescriptor, ResourceKey, ResourceRef
from src.kernel import ModuleSpec, compose, module
from src.resources.module import MODULE

if TYPE_CHECKING:
    from src.kernel import ModuleContext


class _Settings:
    """静态资源装配不读取业务配置。"""

    project_root = Path()

    def resolve[T](self, config_type: type[T]) -> T:
        """纯声明发现无需配置。"""
        raise AssertionError("本测试不应读取配置")


def test_resource_pack_needs_no_builder_and_freezes_its_definition_container() -> None:
    """声明包只发布定义，复制模组不会共享可变资源列表。"""
    descriptor = ResourceDescriptor(ResourceRef(ResourceKey.parse("lab:notes/document/guide"), "1"), "资源包指南")
    items = [descriptor]
    pack = ModuleSpec("notes", resources=cast("tuple[ResourceDescriptor, ...]", items))
    items.clear()
    assert replace(pack, priority=10).resources == (descriptor,)
    assembly = compose(_Settings(), (pack, MODULE))
    assert assembly.get(ResourceCatalog).resolve(descriptor.ref) is descriptor


def test_operation_can_depend_on_the_catalog_that_describes_it() -> None:
    """目录无需构造处理者即可提供查询自身的说明和完整 schema。"""
    definition = OperationDefinition(
        ResourceRef(ResourceKey.parse("lab:resources/query/find"), "1"),
        "发现可用资源",
        {"type": "object", "additionalProperties": False},
    )

    @module(name="owner", provides=bool, declares=OPERATION_CONTRIBUTIONS)
    def owner(context: ModuleContext) -> bool:
        """为测试提供处理者贡献点的唯一声明。"""
        return True

    @module(
        name="reader",
        provides=str,
        requires=ResourceCatalog,
        contributes=OPERATION_CONTRIBUTIONS,
        resources=definition.resource,
    )
    def reader(context: ModuleContext) -> str:
        """实际构造依赖目录，静态说明仍已经可见。"""
        descriptor = context.get(ResourceCatalog).resolve(definition.ref)
        assert descriptor == definition.resource
        return descriptor.description

    assembly = compose(_Settings(), (reader, owner, MODULE))
    assert assembly.get(str) == definition.description


def test_module_resources_must_be_typed_definitions() -> None:
    """无效声明在任何业务构造之前失败。"""
    with pytest.raises(TypeError, match="ResourceDescriptor"):
        ModuleSpec("notes", resources=cast("tuple[ResourceDescriptor, ...]", (object(),)))
