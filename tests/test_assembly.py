from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from aurora import AuroraConfig, assemble_runtime, load_config
from aurora.composer import CompositionContext, InstanceKey, compose
from aurora.composition import compose_project
from aurora.composition.agents import AGENTS
from aurora.composition.ai import MODEL
from aurora.composition.cadence import CADENCE
from aurora.composition.engine import ENGINE_RUNNER
from aurora.composition.memory import MEMORY
from aurora.composition.prompt import PROMPT_ASSEMBLER
from aurora.config import ConfigCollector, ConfigKey, collect_config
from aurora.configuration.agents import AGENTS_CONFIG, AgentsConfig
from aurora.configuration.cadence import CADENCE_CONFIG
from aurora.configuration.engine import ENGINE_CONFIG
from aurora.configuration.prompts import PROMPTS_CONFIG, PromptConfig
from aurora.configuration.runtime import RUNTIME_CONFIG
from aurora.utils.toml import load_toml, text
from src.ai import LiteLLMModelGateway
from src.contracts import MCP_EVENT_RECEIVED, ChatMessage, ModelRequest, TreeStatus

EXPECTED_MAX_DEPTH = 4


@dataclass(slots=True)
class FakeModel:
    requests: list[ModelRequest] = field(default_factory=list)

    async def complete(self, request: ModelRequest) -> ChatMessage:
        self.requests.append(request)
        return ChatMessage.assistant("done")


def test_project_configuration_builds_complete_runtime(configured_project: Path) -> None:
    configuration = load_config(configured_project)
    runtime_configuration = configuration.get(RUNTIME_CONFIG)
    definitions = configuration.get(AGENTS_CONFIG).definitions
    root_definition = next(item for item in definitions if item.definition_id == runtime_configuration.agent)
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
    runtime = assemble_runtime(load_config(configured_project), model)

    async def scenario() -> None:
        await runtime.world.initialize()
        for index in range(5):
            await runtime.record_event(
                event_id=f"event-{index}",
                source="mcp:org.example.background",
                scope="qq:group-cadence",
                kind=MCP_EVENT_RECEIVED,
                summary=f"第 {index + 1} 条消息",
                data={"event_kind": "qq.notice.background"},
            )
        before = runtime.cadence_status()
        await runtime.cadence_trigger()
        after = runtime.cadence_status()

        assert runtime.runtime_status()["trees"]["completed"] == 1
        assert before["pending"] == 0 and after["pending"] == 0
        assert after["cursor"] > before["cursor"]
        assert model.requests[0].messages[1].content == "节律唤起：请初筛最近一小时的世界活动。"
        tree = next(iter(runtime._trees.values()))
        assert tree.node(tree.root_id).definition_id == "builtin.triage"

    asyncio.run(scenario())


def test_memory_snapshot_is_injected_into_prompt_system(configured_project: Path) -> None:
    configuration = load_config(configured_project)
    model = FakeModel()
    runtime = assemble_runtime(configuration, model)

    asyncio.run(runtime.run("hello", tree_id="tree-memory"))

    assert "最近一小时的世界活动" in model.requests[0].messages[0].content


def test_cadence_and_memory_instances_are_composed_and_configured(configured_project: Path) -> None:
    configuration = load_config(configured_project)
    assembly = compose_project(configuration, FakeModel())
    cadence = assembly.get(CADENCE)
    memory = assembly.get(MEMORY)

    assert cadence.enabled is configuration.get(CADENCE_CONFIG).enabled is True
    assert cadence.agent == "builtin.triage"
    assert memory is assembly.get(MEMORY)


def test_assembly_rejects_unavailable_root_tool(configured_project: Path) -> None:
    configuration = load_config(configured_project)
    agents = configuration.get(AGENTS_CONFIG)
    root = agents.definitions[0]
    invalid = configuration.with_value(
        AGENTS_CONFIG,
        AgentsConfig((replace(root, tools=frozenset({*root.tools, "aur.test.missing"})), *agents.definitions[1:])),
    )

    with pytest.raises(ValueError, match="不可用工具"):
        assemble_runtime(invalid, FakeModel())


def test_assembly_rejects_invalid_root_prompt_model_and_delegation_boundary(configured_project: Path) -> None:
    configuration = load_config(configured_project)
    runtime = configuration.get(RUNTIME_CONFIG)
    agents = configuration.get(AGENTS_CONFIG)
    root = agents.definitions[0]

    with pytest.raises(ValueError, match="root 引用了未知 Agent definition"):
        assemble_runtime(configuration.with_value(RUNTIME_CONFIG, replace(runtime, agent="missing")), FakeModel())
    with pytest.raises(ValueError, match="未知 Agent prompt"):
        assemble_runtime(
            configuration.with_value(
                AGENTS_CONFIG,
                AgentsConfig((replace(root, prompt="missing"), *agents.definitions[1:])),
            ),
            FakeModel(),
        )
    with pytest.raises(ValueError, match="未知 model endpoint"):
        assemble_runtime(
            configuration.with_value(
                AGENTS_CONFIG,
                AgentsConfig((replace(root, model="missing"), *agents.definitions[1:])),
            ),
            FakeModel(),
        )
    with pytest.raises(ValueError, match=r"children.*可见性不一致"):
        assemble_runtime(
            configuration.with_value(
                AGENTS_CONFIG,
                AgentsConfig((replace(root, tools=frozenset()), *agents.definitions[1:])),
            ),
            FakeModel(),
        )


def test_configuration_is_pure_data_until_composition_stages_run(configured_project: Path) -> None:
    configuration = load_config(configured_project)
    prompt = configuration.get(PROMPTS_CONFIG)
    engine = configuration.get(ENGINE_CONFIG)
    assembly = compose_project(configuration, FakeModel())

    assert isinstance(configuration, AuroraConfig)
    assert isinstance(prompt, PromptConfig)
    assert engine.max_depth == EXPECTED_MAX_DEPTH
    assert assembly.get(PROMPT_ASSEMBLER) is not None
    assert assembly.get(AGENTS) is not None
    assert assembly.get(ENGINE_RUNNER) is not None


def test_predefined_agents_can_share_prompt_with_different_models_and_tools(configured_project: Path) -> None:
    agents = compose_project(load_config(configured_project), FakeModel()).get(AGENTS)
    worker = agents.get("builtin.worker")
    fast_worker = agents.get("builtin.fast-worker")

    assert worker.prompt_id == fast_worker.prompt_id == "builtin.worker"
    assert worker.model == "quality"
    assert fast_worker.model == "fast"
    assert worker.tools == frozenset({"aur.agent.delegate"})
    assert fast_worker.tools == frozenset()


def test_composition_builds_configured_model_when_caller_does_not_inject_one(configured_project: Path) -> None:
    assembly = compose_project(load_config(configured_project))

    assert isinstance(assembly.get(MODEL), LiteLLMModelGateway)


def test_loader_does_not_fall_back_to_source_template(tmp_path: Path) -> None:
    project_root = Path(__file__).parents[1]
    shutil.copytree(project_root / "config.example", tmp_path / "config.example")

    with pytest.raises(FileNotFoundError, match=r"config[\\/]+runtime\.toml"):
        load_config(tmp_path)


@dataclass(frozen=True, slots=True)
class ExtraConfig:
    value: str


EXTRA_CONFIG = ConfigKey[ExtraConfig]("extra")
EXTRA_INSTANCE = InstanceKey[str]("extra.instance")


def test_new_toml_and_component_only_need_module_registrars(tmp_path: Path) -> None:
    config_directory = tmp_path / "config"
    config_directory.mkdir()
    (config_directory / "extra.toml").write_text('value = "已接入"\n', encoding="utf-8")

    def register_config(configs: ConfigCollector) -> None:
        def parse(path: Path) -> ExtraConfig:
            return ExtraConfig(text(load_toml(path), "value"))

        configs.register(EXTRA_CONFIG, "config/extra.toml", parse)

    def register_component(context: CompositionContext) -> None:
        context.provide(EXTRA_INSTANCE, context.config.get(EXTRA_CONFIG).value)

    configuration = collect_config(tmp_path, (register_config,))
    assembly = compose(configuration, FakeModel(), (register_component,))

    assert configuration.names == ("extra",)
    assert assembly.get(EXTRA_INSTANCE) == "已接入"


def test_registries_reject_duplicate_names_and_missing_dependencies(tmp_path: Path) -> None:
    config_directory = tmp_path / "config"
    config_directory.mkdir()
    (config_directory / "extra.toml").write_text('value = "first"\n', encoding="utf-8")

    def register_twice(configs: ConfigCollector) -> None:
        def parser(path: Path) -> ExtraConfig:
            return ExtraConfig(text(load_toml(path), "value"))

        configs.register(EXTRA_CONFIG, "config/extra.toml", parser)
        configs.register(EXTRA_CONFIG, "config/extra.toml", parser)

    with pytest.raises(ValueError, match="配置重复注册"):
        collect_config(tmp_path, (register_twice,))

    configuration = collect_config(tmp_path, ())

    def require_missing(context: CompositionContext) -> None:
        context.require(EXTRA_INSTANCE)

    with pytest.raises(KeyError, match="组合依赖尚未注册"):
        compose(configuration, FakeModel(), (require_missing,))

    def provide_twice(context: CompositionContext) -> None:
        context.provide(EXTRA_INSTANCE, "first")
        context.provide(EXTRA_INSTANCE, "second")

    with pytest.raises(ValueError, match="实例重复注册"):
        compose(configuration, FakeModel(), (provide_twice,))
