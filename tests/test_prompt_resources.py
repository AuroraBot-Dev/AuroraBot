"""提示词的资源发现、版本核对与实际装配必须使用同一份文本。"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest
from test_assembly import FakeModel
from test_kernel import _Settings

from aurora import load_config
from src.contracts.operation import OPERATION_CONTRIBUTIONS
from src.contracts.pkgs.prompt import PromptAssembler
from src.contracts.pkgs.resources import ResourceCatalog
from src.contracts.prompt import PROMPT_FRAGMENT_CONTRACT, PromptFragment
from src.contracts.resource import ResourceKey, ResourceRef
from src.kernel import compose, module
from src.prompt import PromptAssembler as ConcreteAssembler
from src.prompt import PromptCatalog
from src.prompt.module import MODULE as PROMPT_MODULE
from src.resources.module import MODULE as RESOURCES_MODULE
from src.runtime import assemble_runtime

if TYPE_CHECKING:
    from pathlib import Path

    from src.kernel import ModuleContext


def test_fragment_version_matches_the_exact_normalized_utf8_content() -> None:
    """版本绑定装配真正使用的文本，不绑定可能被修改的文件名。"""
    key = ResourceKey.parse("lab:prompt/agent/research")
    fragment = PromptFragment(key, "\n  核对实验结果。\n")
    assert fragment.content == "核对实验结果。"
    assert fragment.ref == ResourceRef(key, hashlib.sha256(fragment.content.encode("utf-8")).hexdigest())
    assert fragment.resource.ref == fragment.ref
    assert fragment.resource.contract == PROMPT_FRAGMENT_CONTRACT
    assert PromptFragment(key, "核对实验结果。 ").ref == fragment.ref
    assert PromptFragment(key, "先读取实验记录。").ref != fragment.ref


@pytest.mark.parametrize("identity", ["lab:memory/agent/root", "lab:prompt/query/root"])
def test_prompt_fragments_require_a_prompt_domain_and_supported_kind(identity: str) -> None:
    """提示词不能借用另一个领域或操作类别的身份。"""
    with pytest.raises(ValueError, match="prompt 领域"):
        PromptFragment(ResourceKey.parse(identity), "正文")
    with pytest.raises(ValueError, match="不能为空"):
        PromptFragment(ResourceKey.parse("lab:prompt/agent/root"), " \n ")


def test_catalog_preserves_order_and_rejects_duplicate_or_wrong_versions() -> None:
    """片段顺序属于装配事实，相同身份不能在当前目录里同时绑定两个版本。"""
    system = PromptFragment(ResourceKey.parse("lab:prompt/system/identity"), "主体身份")
    context = PromptFragment(ResourceKey.parse("lab:prompt/system/world"), "世界规则")
    agent = PromptFragment(ResourceKey.parse("lab:prompt/agent/research"), "研究方式")
    catalog = PromptCatalog((system, agent, context))
    assert catalog.system == (system.content, context.content)
    assert catalog.for_agent(str(agent.key)) == (system, context, agent)
    assert catalog.get(agent.ref) is agent
    assert catalog.get(ResourceRef(agent.key)) is agent
    with pytest.raises(LookupError, match="版本不存在"):
        catalog.get(PromptFragment(agent.key, "另一个版本").ref)
    with pytest.raises(LookupError, match="版本不存在"):
        catalog.get(ResourceRef(ResourceKey.parse("lab:prompt/agent/missing")))
    with pytest.raises(ValueError, match="身份重复"):
        PromptCatalog((system, agent, PromptFragment(agent.key, "另一个版本")))


def test_project_resource_catalog_matches_the_actual_prompt_fragments(configured_project: Path) -> None:
    """正常装配即能发现提示词，改写源文件不能改变已经装配的目录与文本。"""
    runtime = assemble_runtime(load_config(configured_project), FakeModel())
    assembler = runtime.assembly.get(PromptAssembler)
    resources = runtime.assembly.get(ResourceCatalog)
    fragments = assembler.catalog.fragments
    found = resources.find(domain="prompt")
    assert {descriptor.ref for descriptor in found} == {fragment.ref for fragment in fragments}
    for fragment in fragments:
        assert resources.resolve(fragment.ref, contract=PROMPT_FRAGMENT_CONTRACT) == fragment.resource
    selected = assembler.catalog.for_agent("aurora:prompt/agent/root")
    source = configured_project / "config" / "prompts" / "builtin" / "root.md"
    source.write_text("源文件现在已经改变。", encoding="utf-8")
    assert assembler.catalog.for_agent("aurora:prompt/agent/root") == selected
    assert "源文件现在已经改变。" not in assembler.catalog.agent_prompts["aurora:prompt/agent/root"]


def test_resource_contribution_follows_the_selected_prompt_assembler() -> None:
    """替换装配器时使用获胜者的实际片段，不再读取失选实现的配置文件。"""
    fragments = (
        PromptFragment(ResourceKey.parse("lab:prompt/system/identity"), "自定义身份"),
        PromptFragment(ResourceKey.parse("lab:prompt/agent/root"), "自定义认知方式"),
    )
    selected = ConcreteAssembler(PromptCatalog(fragments))

    @module(name="custom_prompt", provides=PromptAssembler, priority=10, declares=OPERATION_CONTRIBUTIONS)
    def build(context: ModuleContext) -> PromptAssembler:
        """实际能力覆盖默认装配器，测试配置没有任何提示词文件。"""
        return selected

    assembly = compose(_Settings(), (PROMPT_MODULE, RESOURCES_MODULE, build))
    assert assembly.get(PromptAssembler) is selected
    assert {descriptor.ref for descriptor in assembly.get(ResourceCatalog).find(domain="prompt")} == {
        fragment.ref for fragment in fragments
    }
