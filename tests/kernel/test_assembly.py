from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from aurora_agent import ChatMessage as AgentMessage
from aurora_agent import RunSnapshot, RunStats, RunStatus
from aurora_agent import ToolCall as AgentCall
from aurora_bot.agents.config import AgentsConfig
from aurora_bot.ai import LiteLLMModelGateway
from aurora_bot.ai.config import ProvidersConfig
from aurora_bot.contracts import (
    MCP_EVENT_RECEIVED,
    CognitionRequest,
    ToolCall,
    ToolDefinition,
    ToolOutput,
    WorldFrontier,
)
from aurora_bot.runtime import assemble_runtime
from aurora_bot.runtime.presenter import CognitionTextPresenter
from aurora_cli import load_config
from aurora_cli.configs.agents import CONFIG_SPEC as AGENTS_CONFIG
from aurora_cli.configs.engine import CONFIG_SPEC as ENGINE_CONFIG
from aurora_cli.configs.providers import CONFIG_SPEC as PROVIDERS_CONFIG
from aurora_cli.configs.runtime import CONFIG_SPEC as RUNTIME_CONFIG
from tests.support.model import TemplateModel

if TYPE_CHECKING:
    from pathlib import Path


def test_project_config_builds_complete_runtime(configured_project: Path) -> None:
    config = load_config(configured_project)
    model = TemplateModel()
    runtime = assemble_runtime(config, model)

    async def scenario() -> None:
        try:
            result = await runtime.run("hello", run_id="run")
            assert result.status == "completed" and result.run_id == "run"
            definition = runtime.assembly.get("agents").get(runtime.root.agent)
            assert model.requests[0].model == definition.model
            assert [message.role for message in model.requests[0].messages] == ["system", "message"]
            tools = {tool.name for tool in model.requests[0].tools}
            assert {
                "aurora:tool/definition/bot_state",
                "aurora:tool/definition/world_runs",
                "aurora:tool/definition/memory_recall",
                "aurora:tool/definition/artifact_read",
            } <= tools
            assert "aurora:tool/definition/delegate" not in tools
            assert "与你当前工作相关的世界记忆" in model.requests[0].messages[0].content
            assert runtime.assembly.settings is config
        finally:
            await runtime.world.close()

    asyncio.run(scenario())


def test_cadence_trigger_launches_independent_run_after_world_commits(configured_project: Path) -> None:
    model = TemplateModel()
    echoed: list[str] = []
    runtime = assemble_runtime(load_config(configured_project), model, output=echoed.append)
    cadence = runtime.assembly.get("cadence")

    async def scenario() -> None:
        await runtime.world.initialize()
        try:
            for index in range(5):
                await runtime.world.append_commit(
                    commit_id=f"event-{index}",
                    source="mcp:org.example.background",
                    kind=MCP_EVENT_RECEIVED,
                    summary=f"第 {index + 1} 条消息",
                    scopes=frozenset({"qq:group-cadence"}),
                    based_on=WorldFrontier(),
                    data={"event_kind": "qq.notice.background"},
                    occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
                )
            await cadence.evaluate_once()
            assert runtime.runtime_status()["runs"]["completed"] == 1
            assert cadence.status()["pending"] == 0
            assert model.requests[0].resources[0].key.path == "triage"
            assert len(echoed) == 1 and echoed[0].endswith("done")
        finally:
            await runtime.world.close()

    asyncio.run(scenario())


def test_launch_echoes_results_and_uses_a_new_run_for_each_request(configured_project: Path) -> None:
    echoed: list[str] = []
    runtime = assemble_runtime(load_config(configured_project), TemplateModel(), output=echoed.append)

    async def scenario() -> None:
        try:
            first = await runtime.launch(CognitionRequest("第一次", agent="aurora:agent/definition/triage"))
            second = await runtime.launch(CognitionRequest("第二次", agent="aurora:agent/definition/triage"))
            assert first.run_id != second.run_id
            assert echoed == [f"Cadence> [{first.run_id}] done", f"Cadence> [{second.run_id}] done"]
        finally:
            await runtime.world.close()

    asyncio.run(scenario())


def test_presenter_tracks_each_runs_messages_without_duplicate_output() -> None:
    echoed: list[str] = []
    presenter = CognitionTextPresenter(echoed.append)
    snapshot = RunSnapshot(
        "trace",
        RunStatus.RUNNING,
        (
            AgentMessage.message("开始"),
            AgentMessage.assistant(tool_calls=(AgentCall("call", "test:tool/definition/echo", {}),)),
            AgentMessage.tool("call", "结果"),
            AgentMessage.assistant("完成"),
        ),
        (),
        (),
        RunStats(),
        False,
        None,
    )
    presenter.echo(snapshot)
    presenter.echo(snapshot)
    assert echoed == ["  → [trace] test:tool/definition/echo", "  ← [trace] 结果", "Cadence> [trace] 完成"]


def test_presenter_renders_terminal_output(capsys: pytest.CaptureFixture[str]) -> None:
    presenter = CognitionTextPresenter()
    presenter.echo(
        RunSnapshot(
            "trace",
            RunStatus.RUNNING,
            (AgentMessage.message("开始"), AgentMessage.assistant("完成")),
            (),
            (),
            RunStats(),
            False,
            None,
        )
    )
    assert "Cadence> [trace] 完成" in capsys.readouterr().out


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
    definitions = config.get(AGENTS_CONFIG).agents
    config = config.with_value(
        AGENTS_CONFIG,
        AgentsConfig(
            tuple(
                replace(
                    item,
                    tools=("org.aurora.qq:tool/definition/*", "!org.aurora.qq:tool/definition/qq_send_group_message"),
                )
                if item.id == "aurora:agent/definition/root"
                else item
                for item in definitions
            )
        ),
    )
    tools = (
        FakeTool("org.aurora.qq:tool/definition/qq_send_private_message"),
        FakeTool("org.aurora.qq:tool/definition/qq_send_group_message"),
    )
    runtime = assemble_runtime(config, TemplateModel(), tools=tools)
    definition = runtime.assembly.get("agents").get(runtime.root.agent)
    assert definition.tools == frozenset({tools[0].name})


def test_assembly_rejects_unavailable_tools_prompts_and_models(configured_project: Path) -> None:
    config = load_config(configured_project)
    agents = config.get(AGENTS_CONFIG).agents
    first = agents[0]
    for modified, error in (
        (replace(first, tools=("test:tool/definition/missing",)), "引用了未注册名称"),
        (replace(first, prompt="aurora:prompt/agent/missing"), "未知 Agent prompt"),
        (replace(first, model="test:ai/endpoint/missing"), "未知 model endpoint"),
    ):
        with pytest.raises(ValueError, match=error):
            assemble_runtime(config.with_value(AGENTS_CONFIG, AgentsConfig((modified, *agents[1:]))), TemplateModel())
    with pytest.raises(ValueError, match="未知 Agent definition"):
        assemble_runtime(
            config.with_value(RUNTIME_CONFIG, replace(config.get(RUNTIME_CONFIG), agent="missing")), TemplateModel()
        )


def test_profiles_are_independent_and_use_configured_run_limits(configured_project: Path) -> None:
    config = load_config(configured_project)
    runtime = assemble_runtime(config, TemplateModel())
    profiles = runtime.assembly.get("agents").definitions
    assert all("children" not in json.loads(profile.content) for profile in profiles)
    assert runtime.runner.process_definition.max_model_calls == config.get(ENGINE_CONFIG).max_model_calls
    assert runtime.runner.process_definition.max_tool_calls == config.get(ENGINE_CONFIG).max_tool_calls
    assert runtime.assembly.get("memory") is not None
    assert runtime.assembly.get("prompt") is not None


def test_composition_builds_configured_model_when_not_injected(configured_project: Path) -> None:
    runtime = assemble_runtime(load_config(configured_project))
    assert isinstance(runtime.assembly.get("ai"), LiteLLMModelGateway)


def test_assembly_rejects_unusable_provider(configured_project: Path) -> None:
    config = load_config(configured_project)
    providers = config.get(PROVIDERS_CONFIG).providers
    broken = ProvidersConfig(tuple(replace(item, adapter="unknown") for item in providers))
    with pytest.raises(ValueError, match="尚未实现的 adapter"):
        assemble_runtime(config.with_value(PROVIDERS_CONFIG, broken))


def test_loader_does_not_fall_back_to_source_template(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=r"config[\\/]+[a-z]+\.toml"):
        load_config(tmp_path)
