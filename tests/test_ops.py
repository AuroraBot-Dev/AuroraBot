from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from aurora import AuroraRuntime, assemble_runtime, load_config
from ops import ConfigAccess, ConfigSourceRef, OpsRuntime
from ops.contracts import OperationContext, OperationResult, OpsPorts, ParameterLocation, ParameterSpec
from ops.registry import iter_operations, operation
from ops.router import OperationRouter
from src.contracts import ChatMessage, EnvironmentEvent, ModelRequest

if TYPE_CHECKING:
    from pathlib import Path


def _close_runtime(runtime: AuroraRuntime) -> None:
    asyncio.run(runtime.world.close())


@dataclass(slots=True)
class FakeModel:
    responses: list[str] = field(default_factory=lambda: ["完成"])

    async def complete(self, request: ModelRequest) -> ChatMessage:
        _ = request
        return ChatMessage.assistant(self.responses.pop(0))


class FakeEngine:
    def engine_status(self) -> dict[str, object]:
        return {"max_depth": 4, "max_nodes": 32, "max_steps": 256}


class FakeConfig:
    def snapshot(self) -> dict[str, object]:
        return {"sources": [], "read_only": True}

    def read(self, name: str) -> dict[str, object] | None:
        return {"name": name} if name == "runtime" else None


async def _unused_handler(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    _ = context, params
    return OperationResult.success()


def _router() -> OperationRouter:
    return OperationRouter(OpsPorts(FakeEngine(), FakeConfig()))


def test_operation_catalog_is_get_only_and_router_rejects_writes() -> None:
    specs = iter_operations()
    router = _router()

    catalog = asyncio.run(router.execute_path("GET", "/"))
    status = asyncio.run(router.execute_path("GET", "/engine/status"))
    write = asyncio.run(router.execute_path("POST", "/engine/status"))
    missing = asyncio.run(router.execute_path("GET", "/missing"))

    assert specs
    assert all(spec.method == "GET" for spec in specs)
    assert all(parameter.location is not ParameterLocation.BODY for spec in specs for parameter in spec.parameters)
    assert catalog.ok is True
    assert len(catalog.data["operations"]) == len(specs)  # type: ignore[index]
    assert status.data == {"max_depth": 4, "max_nodes": 32, "max_steps": 256}
    assert write.code == "METHOD_NOT_ALLOWED"
    assert missing.code == "NOT_FOUND"
    assert "control" not in OperationResult.success().to_dict()


def test_registry_rejects_write_and_body_operations() -> None:
    with pytest.raises(ValueError, match="只允许注册 GET"):
        operation("POST", "/write", name="write.test")(_unused_handler)
    with pytest.raises(ValueError, match="不能声明 body 参数"):
        operation(
            "GET",
            "/with-body",
            name="body.test",
            parameters=(ParameterSpec("payload", ParameterLocation.BODY, required=True),),
        )(_unused_handler)


def test_read_only_observations_and_parse_errors_through_router(configured_project: Path) -> None:
    runtime = assemble_runtime(load_config(configured_project), FakeModel())
    ops = OpsRuntime(runtime.assembly)
    try:
        parse = asyncio.run(ops.execute("GET", "/engine/status", {"surprise": "1"}))
        invalid = asyncio.run(ops.execute("GET", "/world/stream", {"after": "-1"}))
        agent_detail = asyncio.run(ops.execute("GET", "/agents/builtin.root"))
        agent_tools = asyncio.run(ops.execute("GET", "/agents/builtin.root/tools"))
        agent_missing = asyncio.run(ops.execute("GET", "/agents/absent"))
        config_missing = asyncio.run(ops.execute("GET", "/config/absent"))
        model_missing = asyncio.run(ops.execute("GET", "/models/absent"))
        memory = asyncio.run(ops.execute("GET", "/memory"))
        console = asyncio.run(ops.execute("GET", "/console"))
        mcp = asyncio.run(ops.execute("GET", "/mcp"))

        assert parse.ok is False and parse.code == "PARSE_ERROR"
        assert invalid.ok is False and invalid.code == "INVALID_STREAM"
        assert agent_detail.ok is True and agent_detail.data is not None
        assert agent_tools.ok is True and agent_tools.data is not None
        assert agent_tools.data["tools"] == agent_detail.data["tools"]
        assert agent_missing.ok is False and agent_missing.code == "NOT_FOUND"
        assert config_missing.ok is False and config_missing.code == "NOT_FOUND"
        assert model_missing.ok is False and model_missing.code == "NOT_FOUND"
        assert memory.ok is True and memory.data is not None
        assert console.ok is True and console.data is not None
        assert console.data["enabled"] is True
        assert mcp.ok is True and mcp.data is not None
    finally:
        _close_runtime(runtime)


def test_config_access_is_read_only(configured_project: Path) -> None:
    configuration = load_config(configured_project)
    sources = tuple(ConfigSourceRef(source.name, source.relative_path) for source in configuration.sources)
    access = ConfigAccess(configured_project, sources)

    assert access.snapshot()["read_only"] is True
    assert access.read("apps")["name"] == "apps"  # type: ignore[index]
    assert access.read("absent") is None
    assert not hasattr(access, "set_app_enabled")


def test_config_access_rejects_templates_and_personal_directory_symlink(
    configured_project: Path, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="个人 config"):
        ConfigAccess(configured_project, (ConfigSourceRef("template", "config.example/apps.toml"),))

    linked_root = tmp_path / "linked"
    linked_root.mkdir()
    template = tmp_path / "external-config"
    template.mkdir()
    (template / "apps.toml").write_text("app = []\n", encoding="utf-8")
    (linked_root / "config").symlink_to(template, target_is_directory=True)
    with pytest.raises(ValueError, match="符号链接"):
        ConfigAccess(linked_root, (ConfigSourceRef("apps", "config/apps.toml"),))


def test_ops_runtime_is_built_from_assembly_without_process_controls(configured_project: Path) -> None:
    runtime = assemble_runtime(load_config(configured_project), FakeModel())
    ops = OpsRuntime(runtime.assembly)
    try:
        engine = asyncio.run(ops.execute("GET", "/engine/status"))
        agents = asyncio.run(ops.execute("GET", "/agents"))
        tools = asyncio.run(ops.execute("GET", "/tools"))
        prompts = asyncio.run(ops.execute("GET", "/prompts"))
        models = asyncio.run(ops.execute("GET", "/models"))
        cadence = asyncio.run(ops.execute("GET", "/cadence"))

        assert not hasattr(runtime, "ops")
        assert not hasattr(ops.ports, "process")
        assert not hasattr(ops.ports, "config_reload")
        assert engine.data is not None and engine.data["max_depth"] > 0
        assert agents.data is not None and any(
            item["definition_id"] == "builtin.root" for item in agents.data["agents"]
        )
        assert tools.data is not None and any(item["name"] == "aur.agent.delegate" for item in tools.data["tools"])
        assert prompts.data is not None and "builtin.root" in prompts.data["agent_prompts"]
        assert models.data is not None and any(item["endpoint_id"] == "quality" for item in models.data["endpoints"])
        assert cadence.data is not None and cadence.data["agent"] == "builtin.triage"
    finally:
        _close_runtime(runtime)


def test_world_observation_reads_commits_without_exposing_append(configured_project: Path) -> None:
    runtime = assemble_runtime(load_config(configured_project), FakeModel())
    ops = OpsRuntime(runtime.assembly)
    try:
        asyncio.run(runtime.run("hello", tree_id="tree-stream"))

        page = asyncio.run(ops.execute("GET", "/world/stream", {"after": "0", "limit": "20"}))
        started = asyncio.run(ops.execute("GET", "/world/commits/tree-stream:tree:started"))

        assert page.ok is True
        assert page.data is not None
        assert page.data["commits"][0]["kind"] == "engine.tree.started"
        assert any(commit["kind"] == "engine.tree.completed" for commit in page.data["commits"])
        assert started.data is not None and started.data["kind"] == "engine.tree.started"
        assert not hasattr(ops.ports.world, "record_event")
    finally:
        _close_runtime(runtime)


def test_trusted_runtime_event_entry_does_not_start_tree(configured_project: Path) -> None:
    runtime = assemble_runtime(load_config(configured_project), FakeModel())
    event = EnvironmentEvent(
        "qq-1",
        "qq",
        "qq:group-1",
        "message",
        datetime(2026, 8, 22, 4, tzinfo=UTC),
        "有人发来消息",
        {"message_id": "1"},
    )
    try:
        commit = asyncio.run(runtime.submit_event(event))

        assert commit.summary == "有人发来消息"
        assert runtime.runtime_status()["tree_count"] == 0
    finally:
        _close_runtime(runtime)
