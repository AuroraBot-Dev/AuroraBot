from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from aurora import AuroraConfig, load_config
from aurora.configs.agents import CONFIG_SPEC as AGENTS_CONFIG
from aurora.configs.cadence import CONFIG_SPEC as CADENCE_CONFIG
from aurora.configs.engine import CONFIG_SPEC as ENGINE_CONFIG
from aurora.configs.memory import CONFIG_SPEC as MEMORY_CONFIG
from aurora.configs.providers import CONFIG_SPEC as PROVIDERS_CONFIG
from aurora.configs.runtime import CONFIG_SPEC as RUNTIME_CONFIG
from aurorabot.agents.config import AgentsConfig
from aurorabot.ai import LiteLLMModelGateway
from aurorabot.ai.config import ProvidersConfig
from aurorabot.contracts import (
    MCP_EVENT_RECEIVED,
    ChatMessage,
    Tool,
    ToolCall,
    ToolDefinition,
    ToolOutput,
    TreeLaunchRequest,
    TreeStatus,
    WorldFrontier,
)
from aurorabot.contracts.pkgs.agents import AgentCatalog
from aurorabot.contracts.pkgs.ai import Model
from aurorabot.contracts.pkgs.cadence import Cadence
from aurorabot.contracts.pkgs.engine import AgentTreeRunner
from aurorabot.contracts.pkgs.memory import MemoryReader
from aurorabot.contracts.pkgs.prompt import PromptAssembler
from aurorabot.runtime import assemble_runtime
from tests import PROJECT_ROOT
from tests.support.model import TemplateModel as FakeModel

if TYPE_CHECKING:
    from pathlib import Path

EXPECTED_MAX_DEPTH = 4
EXPECTED_WINDOW_MINUTES = 60
EXPECTED_COMMITS_PER_SCOPE = 50


def test_project_config_builds_complete_runtime(configured_project: Path) -> None:
    config = load_config(configured_project)
    runtime_config = config.get(RUNTIME_CONFIG)
    definitions = config.get(AGENTS_CONFIG).agents
    root_definition = next(item for item in definitions if item.id == runtime_config.agent)
    model = FakeModel()
    runtime = assemble_runtime(config, model)

    result = asyncio.run(runtime.run("hello", tree_id="tree"))

    assert result.status == TreeStatus.COMPLETED
    assert result.tree_id == "tree"
    assert result.node(runtime_config.node_id).definition_id == runtime_config.agent
    assert result.node(runtime_config.node_id).model == root_definition.model
    assert model.requests[0].model == root_definition.model
    assert [tool.name for tool in model.requests[0].tools] == [
        "aurora:tool/definition/artifact_find",
        "aurora:tool/definition/artifact_read",
        "aurora:tool/definition/artifact_stat",
        "aurora:tool/definition/bot_state",
        "aurora:tool/definition/delegate",
        "aurora:tool/definition/goal_set",
        "aurora:tool/definition/memory_exposures",
        "aurora:tool/definition/memory_feedback",
        "aurora:tool/definition/memory_recall",
        "aurora:tool/definition/memory_source",
        "aurora:tool/definition/resources_find",
        "aurora:tool/definition/resources_inspect",
        "aurora:tool/definition/wake_cancel",
        "aurora:tool/definition/wake_schedule",
        "aurora:tool/definition/world_read",
        "aurora:tool/definition/world_scopes",
        "aurora:tool/definition/world_trees",
    ]


def test_cadence_trigger_launches_triage_tree_after_five_world_commits(configured_project: Path) -> None:
    model = FakeModel()
    echoed: list[str] = []
    runtime = assemble_runtime(load_config(configured_project), model, output=echoed.append)
    cadence = runtime.assembly.get(Cadence)

    async def scenario() -> None:
        await runtime.world.initialize()
        for index in range(5):
            await runtime.world.append_commit(
                commit_id=f"event-{index}",
                source="mcp:org.example.background",
                kind=MCP_EVENT_RECEIVED,
                summary=f"第 {index + 1} 条消息",
                scopes=frozenset({"qq:group-cadence"}),
                based_on=WorldFrontier(),
                data={"event_kind": "qq.notice.background"},
                occurred_at=datetime.now(UTC),
            )
        before = cadence.status()
        await cadence.evaluate_once()
        after = cadence.status()

        assert runtime.runtime_status()["trees"]["completed"] == 1
        assert before["pending"] == 0 and after["pending"] == 0
        after_cursor = after["cursor"]
        before_cursor = before["cursor"]
        assert isinstance(after_cursor, int) and isinstance(before_cursor, int)
        assert after_cursor > before_cursor
        assert model.requests[0].messages[1].content == "节律唤起：请初筛最近时间窗口内的世界活动。"
        tree = next(iter(runtime._trees.values()))
        assert tree.node(tree.root_id).definition_id == "aurora:agent/definition/triage"
        assert echoed == ["Cadence> [aurora:agent/definition/triage] done"]

    asyncio.run(scenario())


def test_launch_tree_echoes_root_text_without_external_delivery(configured_project: Path) -> None:
    model = FakeModel()
    echoed: list[str] = []
    runtime = assemble_runtime(load_config(configured_project), model, output=echoed.append)

    async def scenario() -> None:
        result = await runtime.launch_tree(
            TreeLaunchRequest("节律唤起：请初筛。", agent="aurora:agent/definition/triage")
        )
        assert result.status is TreeStatus.COMPLETED
        assert echoed == ["Cadence> [aurora:agent/definition/triage] done"]

    asyncio.run(scenario())


def test_memory_snapshot_is_injected_into_prompt_system(configured_project: Path) -> None:
    config = load_config(configured_project)
    model = FakeModel()
    runtime = assemble_runtime(config, model)

    asyncio.run(runtime.run("hello", tree_id="tree-memory"))

    assert "与你当前工作相关的世界记忆" in model.requests[0].messages[0].content


def test_presenter_traces_tool_calls(configured_project: Path) -> None:
    echoed: list[str] = []
    runtime = assemble_runtime(load_config(configured_project), FakeModel(), output=echoed.append)
    tree = runtime.create_tree("开始")
    tree = tree.append(
        "root", ChatMessage.assistant(tool_calls=(ToolCall("c1", "test:tool/definition/echo", {"value": "hi"}),))
    )
    tree = tree.append("root", ChatMessage.tool("c1", "hi"))
    tree = tree.append("root", ChatMessage.assistant("完成"))

    runtime.presenter.echo(tree)

    assert echoed == [
        "  → [aurora:agent/definition/root] test:tool/definition/echo",
        "  ← [aurora:agent/definition/root] hi",
        "Cadence> [aurora:agent/definition/root] 完成",
    ]


def test_presenter_renders_rich_for_terminal_sink(
    configured_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = assemble_runtime(load_config(configured_project), FakeModel())
    tree = runtime.create_tree("开始")
    tree = tree.append("root", ChatMessage.assistant("完成"))

    runtime.presenter.echo(tree)

    assert "Cadence> [aurora:agent/definition/root] 完成" in capsys.readouterr().out


def test_cadence_and_memory_instances_are_composed_and_configured(configured_project: Path) -> None:
    config = load_config(configured_project)
    assembly = assemble_runtime(config, FakeModel()).assembly
    cadence = assembly.get(Cadence)
    memory = assembly.get(MemoryReader)
    memory_config = config.get(MEMORY_CONFIG)

    assert cadence.enabled is config.get(CADENCE_CONFIG).enabled is True
    assert cadence.agent == "aurora:agent/definition/triage"
    assert memory is assembly.get(MemoryReader)
    assert memory_config.window_minutes == EXPECTED_WINDOW_MINUTES
    assert memory_config.commits_per_scope == EXPECTED_COMMITS_PER_SCOPE
    assert memory_config.scope_include == ()
    assert memory_config.scope_exclude == ()


@dataclass(frozen=True, slots=True)
class FakeTool:
    name: str

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(self.name, "外部工具", {"type": "object"})

    async def execute(self, call: ToolCall) -> ToolOutput:
        return ToolOutput("ok")


def test_agent_tool_patterns_resolve_against_composed_tools(configured_project: Path) -> None:
    config = load_config(configured_project)
    agents = config.get(AGENTS_CONFIG).agents
    with_wildcard = config.with_value(
        AGENTS_CONFIG,
        AgentsConfig(
            tuple(
                replace(
                    item,
                    tools=tuple(
                        (
                            *item.tools,
                            "org.aurora.qq:tool/definition/*",
                            "!org.aurora.qq:tool/definition/qq_send_group_message",
                        )
                    ),
                )
                if item.id == "aurora:agent/definition/root"
                else item
                for item in agents
            )
        ),
    )
    qq_tools: tuple[Tool, ...] = (
        FakeTool("org.aurora.qq:tool/definition/qq_send_private_message"),
        FakeTool("org.aurora.qq:tool/definition/qq_send_group_message"),
    )
    assembly = assemble_runtime(with_wildcard, FakeModel(), tools=qq_tools).assembly
    root_definition = assembly.get(AgentCatalog).get("aurora:agent/definition/root")

    assert "org.aurora.qq:tool/definition/qq_send_private_message" in root_definition.tools
    assert "org.aurora.qq:tool/definition/qq_send_group_message" not in root_definition.tools


def test_assembly_rejects_unavailable_root_tool(configured_project: Path) -> None:
    config = load_config(configured_project)
    agents = config.get(AGENTS_CONFIG).agents
    root = agents[0]
    invalid = config.with_value(
        AGENTS_CONFIG,
        AgentsConfig(tuple((replace(root, tools=tuple((*root.tools, "test:tool/definition/missing"))), *agents[1:]))),
    )

    with pytest.raises(ValueError, match="引用了未注册名称"):
        assemble_runtime(invalid, FakeModel())


def test_assembly_rejects_invalid_root_prompt_model_and_delegation_boundary(configured_project: Path) -> None:
    config = load_config(configured_project)
    runtime = config.get(RUNTIME_CONFIG)
    agents = config.get(AGENTS_CONFIG).agents
    root = agents[0]

    with pytest.raises(ValueError, match="root 引用了未知 Agent definition"):
        assemble_runtime(config.with_value(RUNTIME_CONFIG, replace(runtime, agent="missing")), FakeModel())
    with pytest.raises(ValueError, match="未知 Agent prompt"):
        assemble_runtime(
            config.with_value(
                AGENTS_CONFIG,
                AgentsConfig((replace(root, prompt="aurora:prompt/agent/missing"), *agents[1:])),
            ),
            FakeModel(),
        )
    with pytest.raises(ValueError, match="未知 model endpoint"):
        assemble_runtime(
            config.with_value(
                AGENTS_CONFIG, AgentsConfig((replace(root, model="test:ai/endpoint/missing"), *agents[1:]))
            ),
            FakeModel(),
        )
    with pytest.raises(ValueError, match=r"children.*可见性不一致"):
        assemble_runtime(
            config.with_value(AGENTS_CONFIG, AgentsConfig((replace(root, tools=()), *agents[1:]))),
            FakeModel(),
        )


def test_config_is_pure_data_until_composition_stages_run(configured_project: Path) -> None:
    config = load_config(configured_project)
    engine = config.get(ENGINE_CONFIG)
    assembly = assemble_runtime(config, FakeModel()).assembly

    assert isinstance(config, AuroraConfig)
    assert engine.max_depth == EXPECTED_MAX_DEPTH
    assert assembly.get(PromptAssembler) is not None
    assert assembly.get(AgentCatalog) is not None
    assert assembly.get(AgentTreeRunner) is not None


def test_predefined_agents_form_a_dispatch_chain_with_tool_domains(configured_project: Path) -> None:
    qq_tools: tuple[Tool, ...] = (
        FakeTool("org.aurora.qq:tool/definition/qq_send_private_message"),
        FakeTool("org.aurora.qq:tool/definition/qq_send_group_message"),
        FakeTool("org.aurora.qq:tool/definition/qq_send_forward_message"),
        FakeTool("org.aurora.qq:tool/definition/qq_get_chat_history"),
        FakeTool("org.aurora.qq:tool/definition/qq_mark_chat_read"),
        FakeTool("org.aurora.qq:tool/definition/qq_delete_friend"),
    )
    agents = assemble_runtime(load_config(configured_project), FakeModel(), tools=qq_tools).assembly.get(AgentCatalog)
    triage = agents.get("aurora:agent/definition/triage")
    root = agents.get("aurora:agent/definition/root")
    worker = agents.get("aurora:agent/definition/worker")
    fast_worker = agents.get("aurora:agent/definition/fast-worker")
    reviewer = agents.get("aurora:agent/definition/reviewer")

    assert triage.tools == frozenset({"aurora:tool/definition/delegate"})
    assert triage.children == frozenset({"aurora:agent/definition/root", "aurora:agent/definition/fast-worker"})
    assert root.tools == frozenset(
        {
            "aurora:tool/definition/artifact_find",
            "aurora:tool/definition/artifact_read",
            "aurora:tool/definition/artifact_stat",
            "aurora:tool/definition/bot_state",
            "aurora:tool/definition/delegate",
            "aurora:tool/definition/goal_set",
            "aurora:tool/definition/memory_exposures",
            "aurora:tool/definition/memory_feedback",
            "aurora:tool/definition/memory_recall",
            "aurora:tool/definition/memory_source",
            "aurora:tool/definition/resources_find",
            "aurora:tool/definition/resources_inspect",
            "aurora:tool/definition/wake_cancel",
            "aurora:tool/definition/wake_schedule",
            "aurora:tool/definition/world_read",
            "aurora:tool/definition/world_scopes",
            "aurora:tool/definition/world_trees",
        }
    )
    assert root.children == frozenset(
        {
            "aurora:agent/definition/worker",
            "aurora:agent/definition/fast-worker",
            "aurora:agent/definition/reviewer",
            "aurora:agent/definition/chat",
            "aurora:agent/definition/memory",
        }
    )
    memory = agents.get("aurora:agent/definition/memory")
    assert {"aurora:tool/definition/memory_source", "aurora:tool/definition/memory_feedback"} <= memory.tools
    assert memory.children == frozenset()
    assert worker.model == "aurora:ai/endpoint/quality"
    assert worker.children == frozenset({"aurora:agent/definition/reviewer", "aurora:agent/definition/fast-worker"})
    assert "org.aurora.qq:tool/definition/qq_send_private_message" in worker.tools
    assert "org.aurora.qq:tool/definition/qq_delete_friend" in worker.tools
    assert fast_worker.model == "aurora:ai/endpoint/fast"
    assert fast_worker.prompt_id == "aurora:prompt/agent/fast"
    assert fast_worker.children == frozenset()
    assert fast_worker.tools == frozenset(
        {
            "org.aurora.qq:tool/definition/qq_send_private_message",
            "org.aurora.qq:tool/definition/qq_send_group_message",
            "org.aurora.qq:tool/definition/qq_get_chat_history",
            "org.aurora.qq:tool/definition/qq_mark_chat_read",
        }
    )
    assert reviewer.tools == frozenset() and reviewer.children == frozenset()


def test_composition_builds_configured_model_when_caller_does_not_inject_one(configured_project: Path) -> None:
    assembly = assemble_runtime(load_config(configured_project)).assembly

    assert isinstance(assembly.get(Model), LiteLLMModelGateway)


def test_assembly_rejects_agent_model_whose_provider_is_unusable(configured_project: Path) -> None:
    config = load_config(configured_project)
    providers = config.get(PROVIDERS_CONFIG).providers
    broken = ProvidersConfig(
        tuple(
            replace(item, adapter="unknown") if item.name == "aurora:ai/provider/deepseek" else item
            for item in providers
        )
    )

    with pytest.raises(ValueError, match="尚未实现的 adapter"):
        assemble_runtime(config.with_value(PROVIDERS_CONFIG, broken))


def test_loader_does_not_fall_back_to_source_template(tmp_path: Path) -> None:
    project_root = PROJECT_ROOT
    shutil.copytree(project_root / "config.example", tmp_path / "config.example")

    with pytest.raises(FileNotFoundError, match=r"config[\\/]+[a-z]+\.toml"):
        load_config(tmp_path)


def test_assembly_bundles_the_project_config(configured_project: Path) -> None:
    config = load_config(configured_project)
    assembly = assemble_runtime(config, FakeModel()).assembly

    assert assembly.settings is config
