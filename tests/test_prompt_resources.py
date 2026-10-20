"""提示词的资源发现、版本核对与实际装配必须使用同一份文本。"""

from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING

import pytest
from model_support import fake_endpoint
from test_assembly import FakeModel
from test_kernel import _Settings

from aurora import load_config
from aurorabot.artifacts.module import MODULE as ARTIFACTS_MODULE
from aurorabot.artifacts.store import FileArtifactStore
from aurorabot.contracts import AgentDefinition, AgentTree, ChatMessage, ModelRequest
from aurorabot.contracts.operation import OPERATION_CONTRIBUTIONS
from aurorabot.contracts.pkgs.artifacts import ArtifactStore
from aurorabot.contracts.pkgs.prompt import PromptAssembler
from aurorabot.contracts.pkgs.resources import ResourceCatalog
from aurorabot.contracts.prompt import PROMPT_FRAGMENT_CONTRACT, PromptAssembly, PromptFragment
from aurorabot.contracts.resource import ResourceKey, ResourceRef
from aurorabot.kernel import compose_managed, module
from aurorabot.prompt import PromptAssembler as ConcreteAssembler
from aurorabot.prompt import PromptCatalog
from aurorabot.prompt.module import MODULE as PROMPT_MODULE
from aurorabot.resource_content.module import MODULE as CONTENT_MODULE
from aurorabot.resources.module import MODULE as RESOURCES_MODULE
from aurorabot.runtime import assemble_runtime

if TYPE_CHECKING:
    from pathlib import Path

    from aurorabot.kernel import ModuleContext


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


def test_resource_contribution_follows_the_selected_prompt_assembler(tmp_path: Path) -> None:
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

    async def scenario() -> None:
        """资源声明与正文存储都跟随选中实例，默认配置文件不参与读取。"""
        store = FileArtifactStore(tmp_path / "content")
        lifecycle = await compose_managed(
            _Settings(),
            (PROMPT_MODULE, RESOURCES_MODULE, ARTIFACTS_MODULE, CONTENT_MODULE, build),
            instances=((ArtifactStore, store),),
        )
        try:
            assembly = lifecycle.assembly
            assert assembly.get(PromptAssembler) is selected
            assert {descriptor.ref for descriptor in assembly.get(ResourceCatalog).find(domain="prompt")} == {
                fragment.ref for fragment in fragments
            }
            await lifecycle.activate(asyncio.Event())
            for fragment in fragments:
                assert (await store.read(fragment.ref)).content == fragment.content.encode("utf-8")
        finally:
            await lifecycle.close()

    asyncio.run(scenario())


def test_assembly_records_only_the_selected_fragments_in_their_actual_order() -> None:
    """未采用的 Agent 提示词不进入请求来源，系统片段顺序不可被资源排序替换。"""
    first = PromptFragment(ResourceKey.parse("lab:prompt/system/z"), "第一个系统片段")
    last = PromptFragment(ResourceKey.parse("lab:prompt/system/a"), "第二个系统片段")
    selected = PromptFragment(ResourceKey.parse("lab:prompt/agent/selected"), "选定角色")
    other = PromptFragment(ResourceKey.parse("lab:prompt/agent/other"), "其他角色")
    assembler = ConcreteAssembler(PromptCatalog((first, other, last, selected)))
    agent = AgentDefinition(
        "lab:agent/definition/root", "主体", str(selected.key), "test:ai/endpoint/model", frozenset(), frozenset()
    )
    result = assembler.assemble(AgentTree.create("tree", "root", agent, "开始"), "root")
    assert result.resources == (first.ref, last.ref, selected.ref)
    assert result.messages[0].content == "第一个系统片段\n\n第二个系统片段\n\n选定角色"


@pytest.mark.parametrize("fixed", [False, True])
def test_model_and_assembly_reject_unresolved_or_duplicate_resources(fixed: bool) -> None:
    """请求审计必须有明确版本，重复引用也不能制造错误的来源计数。"""
    key = ResourceKey.parse("lab:prompt/agent/root")
    refs = (ResourceRef(key, "version"),) * 2 if fixed else (ResourceRef(key),)
    message = ChatMessage.system("主体身份")
    with pytest.raises(ValueError, match="输入资源"):
        PromptAssembly((message,), resources=refs)
    with pytest.raises(ValueError, match="输入资源"):
        ModelRequest(fake_endpoint("test:ai/endpoint/model"), (message,), resources=refs)


def test_actual_model_request_and_world_audit_keep_the_frozen_prompt_versions(configured_project: Path) -> None:
    """源文件改变后，模型输入与记录仍绑定装配时实际采用的内容版本。"""

    async def scenario() -> None:
        """读取实际世界事实，避免只检查组装器返回的元数据。"""
        model = FakeModel()
        runtime = assemble_runtime(load_config(configured_project), model)
        assembler = runtime.assembly.get(PromptAssembler)
        selected = assembler.catalog.for_agent("aurora:prompt/agent/root")
        source = configured_project / "config" / "prompts" / "builtin" / "root.md"
        source.write_text("这份新正文尚未用于当前运行。", encoding="utf-8")
        try:
            tree = await runtime.run("检查提示词来源", tree_id="prompt-source")
            assert len(model.requests) == 1
            request = model.requests[0]
            assert request.resources == (
                tree.node(tree.root_id).definition_ref,
                *(fragment.ref for fragment in selected),
                request.endpoint.ref,
                request.endpoint.provider.ref,
                *(tool.ref for tool in request.tools),
            )
            assert "这份新正文尚未用于当前运行。" not in request.messages[0].content
            record = await runtime.world.commit(f"prompt-source:{tree.root_id}:model:0:requested")
            assert record is not None
            assert list(record.data["resources"]) == [
                {"key": str(ref.key), "revision": ref.revision} for ref in request.resources
            ]
        finally:
            await runtime.world.close()

    asyncio.run(scenario())
