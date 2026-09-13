from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aurora import AuroraConfig, load_config
from aurora.configuration.agents import AGENTS_CONFIG
from aurora.configuration.cadence import CADENCE_CONFIG
from aurora.configuration.engine import ENGINE_CONFIG
from aurora.configuration.memory import MEMORY_CONFIG
from aurora.configuration.runtime import RUNTIME_CONFIG
from src.agents.config import AgentsConfig
from src.ai import LiteLLMModelGateway
from src.contracts import (
    MCP_EVENT_RECEIVED,
    AgentCatalog,
    AgentTreeRunner,
    Cadence,
    ChatMessage,
    MemoryReader,
    Model,
    ModelRequest,
    PromptAssembler,
    Tool,
    ToolCall,
    ToolDefinition,
    ToolOutput,
    TreeLaunchRequest,
    TreeStatus,
    WorldFrontier,
)
from src.runtime import assemble_runtime

EXPECTED_MAX_DEPTH = 4
EXPECTED_WINDOW_MINUTES = 60
EXPECTED_COMMITS_PER_SCOPE = 50


@dataclass(slots=True)
class FakeModel:
    requests: list[ModelRequest] = field(default_factory=list)

    async def complete(self, request: ModelRequest) -> ChatMessage:
        self.requests.append(request)
        return ChatMessage.assistant("done")


def test_project_configuration_builds_complete_runtime(configured_project: Path) -> None:
    configuration = load_config(configured_project)
    runtime_configuration = configuration.get(RUNTIME_CONFIG)
    definitions = configuration.get(AGENTS_CONFIG).agents
    root_definition = next(item for item in definitions if item.id == runtime_configuration.agent)
    model = FakeModel()
    runtime = assemble_runtime(configuration, model)

    result = asyncio.run(runtime.run("hello", tree_id="tree"))

    assert result.status == TreeStatus.COMPLETED
    assert result.tree_id == "tree"
    assert result.node(runtime_configuration.node_id).definition_id == runtime_configuration.agent
    assert result.node(runtime_configuration.node_id).model == root_definition.model
    assert model.requests[0].model == root_definition.model
    assert [tool.name for tool in model.requests[0].tools] == [
        "aur.agent.delegate",
        "aur.serv.world.read",
        "aur.serv.world.trees",
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
        assert tree.node(tree.root_id).definition_id == "builtin.triage"
        assert echoed == ["Cadence> [builtin.triage] done"]

    asyncio.run(scenario())


def test_launch_tree_echoes_root_text_without_external_delivery(configured_project: Path) -> None:
    model = FakeModel()
    echoed: list[str] = []
    runtime = assemble_runtime(load_config(configured_project), model, output=echoed.append)

    async def scenario() -> None:
        result = await runtime.launch_tree(TreeLaunchRequest("节律唤起：请初筛。", agent="builtin.triage"))
        assert result.status is TreeStatus.COMPLETED
        assert echoed == ["Cadence> [builtin.triage] done"]

    asyncio.run(scenario())


def test_memory_snapshot_is_injected_into_prompt_system(configured_project: Path) -> None:
    configuration = load_config(configured_project)
    model = FakeModel()
    runtime = assemble_runtime(configuration, model)

    asyncio.run(runtime.run("hello", tree_id="tree-memory"))

    assert "最近时间窗口内的世界活动" in model.requests[0].messages[0].content


def test_presenter_traces_tool_calls(configured_project: Path) -> None:
    echoed: list[str] = []
    runtime = assemble_runtime(load_config(configured_project), FakeModel(), output=echoed.append)
    tree = runtime.create_tree("开始")
    tree = tree.append("root", ChatMessage.assistant(tool_calls=(ToolCall("c1", "aur.test.echo", {"value": "hi"}),)))
    tree = tree.append("root", ChatMessage.tool("c1", "hi"))
    tree = tree.append("root", ChatMessage.assistant("完成"))

    runtime.presenter.echo(tree)

    assert echoed == [
        "  → [builtin.root] aur.test.echo",
        "  ← [builtin.root] hi",
        "Cadence> [builtin.root] 完成",
    ]


def test_presenter_renders_rich_for_terminal_sink(
    configured_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = assemble_runtime(load_config(configured_project), FakeModel())
    tree = runtime.create_tree("开始")
    tree = tree.append("root", ChatMessage.assistant("完成"))

    runtime.presenter.echo(tree)

    assert "Cadence> [builtin.root] 完成" in capsys.readouterr().out


def test_cadence_and_memory_instances_are_composed_and_configured(configured_project: Path) -> None:
    configuration = load_config(configured_project)
    assembly = assemble_runtime(configuration, FakeModel()).assembly
    cadence = assembly.get(Cadence)
    memory = assembly.get(MemoryReader)
    memory_config = configuration.get(MEMORY_CONFIG)

    assert cadence.enabled is configuration.get(CADENCE_CONFIG).enabled is True
    assert cadence.agent == "builtin.triage"
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
    configuration = load_config(configured_project)
    agents = configuration.get(AGENTS_CONFIG).agents
    with_wildcard = configuration.with_value(
        AGENTS_CONFIG,
        AgentsConfig(
            tuple(
                replace(
                    item,
                    tools=tuple(
                        (*item.tools, "aur.mcp.org.aurora.qq.*", "!aur.mcp.org.aurora.qq.qq_send_group_message")
                    ),
                )
                if item.id == "builtin.root"
                else item
                for item in agents
            )
        ),
    )
    qq_tools: tuple[Tool, ...] = (
        FakeTool("aur.mcp.org.aurora.qq.qq_send_private_message"),
        FakeTool("aur.mcp.org.aurora.qq.qq_send_group_message"),
    )
    assembly = assemble_runtime(with_wildcard, FakeModel(), tools=qq_tools).assembly
    root_definition = assembly.get(AgentCatalog).get("builtin.root")

    assert "aur.mcp.org.aurora.qq.qq_send_private_message" in root_definition.tools
    assert "aur.mcp.org.aurora.qq.qq_send_group_message" not in root_definition.tools


def test_assembly_rejects_unavailable_root_tool(configured_project: Path) -> None:
    configuration = load_config(configured_project)
    agents = configuration.get(AGENTS_CONFIG).agents
    root = agents[0]
    invalid = configuration.with_value(
        AGENTS_CONFIG,
        AgentsConfig(tuple((replace(root, tools=tuple((*root.tools, "aur.test.missing"))), *agents[1:]))),
    )

    with pytest.raises(ValueError, match="引用了未注册名称"):
        assemble_runtime(invalid, FakeModel())


def test_assembly_rejects_invalid_root_prompt_model_and_delegation_boundary(configured_project: Path) -> None:
    configuration = load_config(configured_project)
    runtime = configuration.get(RUNTIME_CONFIG)
    agents = configuration.get(AGENTS_CONFIG).agents
    root = agents[0]

    with pytest.raises(ValueError, match="root 引用了未知 Agent definition"):
        assemble_runtime(configuration.with_value(RUNTIME_CONFIG, replace(runtime, agent="missing")), FakeModel())
    with pytest.raises(ValueError, match="未知 Agent prompt"):
        assemble_runtime(
            configuration.with_value(AGENTS_CONFIG, AgentsConfig((replace(root, prompt="missing"), *agents[1:]))),
            FakeModel(),
        )
    with pytest.raises(ValueError, match="未知 model endpoint"):
        assemble_runtime(
            configuration.with_value(AGENTS_CONFIG, AgentsConfig((replace(root, model="missing"), *agents[1:]))),
            FakeModel(),
        )
    with pytest.raises(ValueError, match=r"children.*可见性不一致"):
        assemble_runtime(
            configuration.with_value(AGENTS_CONFIG, AgentsConfig((replace(root, tools=()), *agents[1:]))),
            FakeModel(),
        )


def test_configuration_is_pure_data_until_composition_stages_run(configured_project: Path) -> None:
    configuration = load_config(configured_project)
    engine = configuration.get(ENGINE_CONFIG)
    assembly = assemble_runtime(configuration, FakeModel()).assembly

    assert isinstance(configuration, AuroraConfig)
    assert engine.max_depth == EXPECTED_MAX_DEPTH
    assert assembly.get(PromptAssembler) is not None
    assert assembly.get(AgentCatalog) is not None
    assert assembly.get(AgentTreeRunner) is not None


def test_predefined_agents_form_a_dispatch_chain_with_tool_domains(configured_project: Path) -> None:
    qq_tools: tuple[Tool, ...] = (
        FakeTool("aur.mcp.org.aurora.qq.qq_send_private_message"),
        FakeTool("aur.mcp.org.aurora.qq.qq_send_group_message"),
        FakeTool("aur.mcp.org.aurora.qq.qq_send_forward_message"),
        FakeTool("aur.mcp.org.aurora.qq.qq_get_chat_history"),
        FakeTool("aur.mcp.org.aurora.qq.qq_mark_chat_read"),
        FakeTool("aur.mcp.org.aurora.qq.qq_delete_friend"),
    )
    agents = assemble_runtime(load_config(configured_project), FakeModel(), tools=qq_tools).assembly.get(AgentCatalog)
    triage = agents.get("builtin.triage")
    root = agents.get("builtin.root")
    worker = agents.get("builtin.worker")
    fast_worker = agents.get("builtin.fast-worker")
    reviewer = agents.get("builtin.reviewer")

    assert triage.tools == frozenset({"aur.agent.delegate"})
    assert triage.children == frozenset({"builtin.root", "builtin.fast-worker"})
    assert root.tools == frozenset({"aur.agent.delegate", "aur.serv.world.read", "aur.serv.world.trees"})
    assert root.children == frozenset({"builtin.worker", "builtin.fast-worker", "builtin.reviewer", "builtin.chat"})
    assert worker.model == "quality"
    assert worker.children == frozenset({"builtin.reviewer", "builtin.fast-worker"})
    assert "aur.mcp.org.aurora.qq.qq_send_private_message" in worker.tools
    assert "aur.mcp.org.aurora.qq.qq_delete_friend" in worker.tools
    assert fast_worker.model == "fast"
    assert fast_worker.prompt_id == "builtin.fast"
    assert fast_worker.children == frozenset()
    assert fast_worker.tools == frozenset(
        {
            "aur.mcp.org.aurora.qq.qq_send_private_message",
            "aur.mcp.org.aurora.qq.qq_send_group_message",
            "aur.mcp.org.aurora.qq.qq_get_chat_history",
            "aur.mcp.org.aurora.qq.qq_mark_chat_read",
        }
    )
    assert reviewer.tools == frozenset() and reviewer.children == frozenset()


def test_composition_builds_configured_model_when_caller_does_not_inject_one(configured_project: Path) -> None:
    assembly = assemble_runtime(load_config(configured_project)).assembly

    assert isinstance(assembly.get(Model), LiteLLMModelGateway)


def test_loader_does_not_fall_back_to_source_template(tmp_path: Path) -> None:
    project_root = Path(__file__).parents[1]
    shutil.copytree(project_root / "config.example", tmp_path / "config.example")

    with pytest.raises(FileNotFoundError, match=r"config[\\/]+[a-z]+\.toml"):
        load_config(tmp_path)


def test_assembly_bundles_the_project_configuration(configured_project: Path) -> None:
    configuration = load_config(configured_project)
    assembly = assemble_runtime(configuration, FakeModel()).assembly

    assert assembly.settings is configuration
