"""模组声明正文固定完整约束，并通过统一资源链路发布。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from aurora_bot.contracts import ContributionKey
from aurora_bot.contracts.module_manifest import MODULE_MANIFEST_CONTRACT, ModuleManifest
from aurora_bot.contracts.resource import ResourceDescriptor, ResourceKey, ResourceRef
from aurora_bot.contracts.scope import ScopeDeclaration, ScopeKind
from aurora_bot.kernel import CONSTRUCT, READY, ModuleSpec, Ordering, module

if TYPE_CHECKING:
    from aurora_bot.kernel import ModuleContext

_RESOURCE = ResourceDescriptor(
    ResourceRef(ResourceKey.parse("lab:example/query/read"), "1"),
    "读取示例",
    metadata={"parameters": {"type": "object", "properties": {"count": {"type": "integer"}}}},
)
_CONTRIBUTION = ContributionKey[str]("lab:example/contribution/values")


def _spec() -> ModuleSpec:
    """声明真实构造器，清单记录作者钩子的来源。"""

    @module(name="example", provides="str", manifest=ModuleManifest(namespace="lab"), resources=_RESOURCE)
    def build(context: ModuleContext) -> str:
        """构造器在公开清单中保留原始身份。"""
        del context
        return "example"

    return build


def test_module_content_and_catalog_description_bind_the_same_fixed_declaration() -> None:
    """目录、契约与正文共享身份和版本，目录不会内联整份资源 schema。"""
    spec = _spec()
    data = json.loads(spec.content)
    assert spec.resource.ref.key == spec.key
    assert spec.resource.ref.revision == hashlib.sha256(spec.content).hexdigest()
    assert spec.resource.contract == MODULE_MANIFEST_CONTRACT
    assert data["key"] == spec.module_id
    assert data["version"] == spec.manifest.version
    assert data["provides"] == ["str"]
    assert data["resources"][0]["metadata"]["parameters"]["properties"]["count"] == {"type": "integer"}
    assert data["lifecycle"][0]["hook"] == f"{__name__}._spec.<locals>.build"
    assert spec.resource.metadata["declared_capabilities"]["provides"] == ("str",)
    assert spec.resource.metadata["declared_resources"][0]["key"] == str(_RESOURCE.ref.key)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "other"),
        ("manifest", ModuleManifest("2", namespace="lab")),
        ("manifest", ModuleManifest(kernel_api=">=1,<3", namespace="lab")),
        ("manifest", ModuleManifest(namespace="other")),
        ("provides", ("int",)),
        ("requires", ("int",)),
        ("contributes", (_CONTRIBUTION,)),
        ("consumes", (_CONTRIBUTION,)),
        ("declares", (_CONTRIBUTION,)),
        ("owns_scopes", ("lab:world/owned",)),
        ("observes_scopes", ("lab:world/observed",)),
        ("scopes", (ScopeDeclaration("lab:world/*", ScopeKind.RESOURCE, "示例世界"),)),
        ("resources", (replace(_RESOURCE, description="另一份说明"),)),
        ("resources", (replace(_RESOURCE, metadata={"parameters": {"type": "string"}}),)),
        ("priority", 10),
        ("optional", True),
        ("order", (Ordering(READY, after=("str",)),)),
    ],
)
def test_module_content_version_changes_with_each_declaration_dimension(field: str, value: object) -> None:
    """同名改动不能沿用旧声明摘要，发布号相同也必须能识别结构变化。"""
    original = _spec()
    changed = replace(original, **{field: value})
    assert changed.content != original.content
    assert changed.resource.ref != original.resource.ref


def test_module_content_freezes_hook_order_and_does_not_retain_mutable_input() -> None:
    """阶段字典的书写顺序不改变声明版本，外部后续修改不能改写正文。"""
    base = _spec()

    async def ready(context: ModuleContext) -> None:
        """另一个实际钩子属于完整生命周期声明。"""
        del context

    hooks = {CONSTRUCT: base.hooks[CONSTRUCT], READY: ready}
    original = replace(base, hooks=hooks)
    equivalent = replace(base, hooks=dict(reversed(tuple(hooks.items()))))
    assert original.content == equivalent.content
    assert original.resource == equivalent.resource
    assert original.resource.ref != base.resource.ref
    saved = original.content
    hooks.clear()
    assert original.content == saved
    assert READY in original.hooks
