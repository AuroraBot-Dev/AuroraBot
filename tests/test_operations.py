# ruff: noqa: ARG002, PLR2004
"""操作体系：RESTful 资源树与文本命令同构。"""

from __future__ import annotations

import asyncio
from typing import Any

from ops.registry import catalog_entries, iter_operations
from ops.router import OperationRouter
from src.contracts import (
    CommandControl,
    CommandResult,
    InputOrigin,
    OperationResult,
    OperationSpec,
    PanelRuntime,
    RuntimeInput,
)


class _FakeEngine:
    def __init__(self) -> None:
        self.sessions: dict[str, list[dict[str, Any]]] = {}
        self.tasks: dict[str, dict[str, Any]] = {"t-1": {"task": {"task_id": "t-1", "root_agent_id": "a-1"}}}
        self.agents: dict[str, dict[str, Any]] = {"a-1": {"agent": {"agent_id": "a-1"}}}
        self.shutdown_called = False

    async def submit_amp(self, value: object) -> str:
        return "amp-1"

    async def submit_conversation(self, request: RuntimeInput, text: str) -> str:
        return f"conv:{text}"

    async def pump(self, max_turns: int | None = None) -> dict[str, Any]:
        return {"pumped_turns": max_turns, "admitted_task_ids": ["t-1"]}

    def status(self) -> dict[str, Any]:
        return {"active_tasks": 1}

    def task(self, task_id: str) -> dict[str, Any] | None:
        return self.tasks.get(task_id)

    def agent(self, agent_id: str) -> dict[str, Any] | None:
        return self.agents.get(agent_id)

    def output_stream(self, cursor: int = 0, *, limit: int = 64) -> Any:
        from src.contracts import OutputStreamPage

        return OutputStreamPage(items=(), next_cursor=cursor)

    def output_tail_cursor(self) -> int:
        return 0

    def list_tasks(self, *, status: str | None = None, limit: int = 64) -> list[dict[str, Any]]:
        return [item["task"] for item in self.tasks.values()]

    def list_agents(self, *, limit: int = 64) -> list[dict[str, Any]]:
        return [item["agent"] for item in self.agents.values()]

    def query_events(
        self,
        *,
        session_id: str | None = None,
        task_id: str | None = None,
        event_type: str | None = None,
        after_id: int = 0,
        limit: int = 64,
    ) -> list[dict[str, Any]]:
        return []

    def session_export(self, session_id: str) -> dict[str, Any] | None:
        if session_id not in self.sessions:
            return None
        return {"session_id": session_id, "events": self.sessions[session_id], "outputs": []}


class _FakeMemory:
    def history(self, *, scope: str | None = None, limit: int = 32) -> dict[str, Any]:
        return {
            "scope": scope,
            "window": [{"role": "user", "content": "hi", "at": "now"}],
            "summaries": [],
            "facts": [],
        }

    async def search(self, query: str, *, scope: str | None = None, limit: int = 8) -> list[dict[str, Any]]:
        return [{"kind": "fact", "content": query, "hits": 1}]

    def status(self) -> dict[str, Any]:
        return {"enabled": True, "window_messages": 1, "summaries": 0, "facts": 0, "scopes": ["s1"]}


class _FakeAi:
    async def cost(self) -> dict[str, Any]:
        return {"total_cost": 1.5, "by_role": {"fast": {"count": 1, "cost": 1.5}}, "by_model": {}, "by_status": {}}

    async def models(self) -> list[dict[str, Any]]:
        return [{"role": "fast", "model": "p/m", "capabilities": ["chat"]}]

    def roles(self) -> list[dict[str, Any]]:
        return [{"role": "fast", "model": "p/m"}]


class _FakeConfig:
    def snapshot(self) -> dict[str, Any]:
        return {"profile": "test", "agents": [{"id": "root", "model_role": "fast"}]}

    def prompt_for(self, role: str) -> dict[str, Any] | None:
        if role == "missing":
            return None
        return {"role": role, "text": f"prompt:{role}"}

    def extensions(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "ext-1",
                "version": "1.0",
                "enabled": True,
                "factory": "aurora.builtin.control",
                "faces": ["control_action"],
                "capabilities": [],
            }
        ]

    def apps(self) -> list[dict[str, Any]]:
        return [
            {
                "package": "app-1",
                "enabled": False,
                "transport": "stdio",
                "working_dir": "src/apps/app-1",
                "command": ["uv", "run", "app-1"],
                "env": [],
                "url": None,
                "auth_env": None,
                "timeout_seconds": 30,
            }
        ]

    def set_extension_enabled(self, extension_id: str, *, enabled: bool) -> dict[str, Any]:
        if extension_id != "ext-1":
            raise KeyError(f"id 未找到: {extension_id}")
        return {"id": extension_id, "enabled": enabled, "requires_restart": True}

    def set_app_enabled(self, package: str, *, enabled: bool) -> dict[str, Any]:
        if package != "app-1":
            raise KeyError(f"package 未找到: {package}")
        return {"package": package, "enabled": enabled, "requires_restart": True}


def _runtime() -> PanelRuntime:
    return PanelRuntime(
        engine=_FakeEngine(),
        memory=_FakeMemory(),
        ai=_FakeAi(),
        config=_FakeConfig(),
        shutdown=lambda: None,
    )


def _specs() -> dict[tuple[str, str], OperationSpec]:
    return {(spec.method, spec.path): spec for spec in iter_operations()}


async def _execute(
    router: OperationRouter, method: str, path: str, params: dict[str, Any]
) -> tuple[OperationResult, dict[str, Any]]:
    spec, path_params, mismatch = router.resolve(method, path)
    assert spec is not None and not mismatch
    merged = dict(path_params or {})
    merged.update(params)
    result = await router.execute(spec, merged)
    return result, result.data or {}


def test_catalog_self_describes_resources() -> None:
    entries = catalog_entries()
    names = {(entry["method"], entry["path"]) for entry in entries}
    assert ("GET", "/engine/status") in names
    assert ("GET", "/engine/tasks/{task_id}") in names
    assert ("GET", "/memory/history") in names
    assert ("GET", "/ai/cost") in names
    assert ("GET", "/config/snapshot") in names
    assert ("GET", "/prompts/{role}") in names
    assert ("POST", "/messages") in names
    assert ("POST", "/engine/shutdown") in names
    assert ("GET", "/engine/events") in names
    assert ("POST", "/engine/events") in names
    assert ("GET", "/extensions") in names
    assert ("POST", "/extensions/{extension_id}/enabled") in names
    assert ("GET", "/apps") in names
    assert ("POST", "/apps/{package}/enabled") in names


def test_extensions_and_apps_list_and_toggle() -> None:
    async def scenario() -> None:
        router = OperationRouter(_runtime())

        extensions, extensions_data = await _execute(router, "GET", "/extensions", {})
        assert extensions.ok and extensions_data["count"] == 1
        assert extensions_data["extensions"][0]["id"] == "ext-1"

        apps, apps_data = await _execute(router, "GET", "/apps", {})
        assert apps.ok and apps_data["count"] == 1
        assert apps_data["apps"][0]["package"] == "app-1"

        toggled_ext, toggled_ext_data = await _execute(router, "POST", "/extensions/ext-1/enabled", {"enabled": False})
        assert toggled_ext.ok and toggled_ext_data == {
            "id": "ext-1",
            "enabled": False,
            "requires_restart": True,
        }

        toggled_app, toggled_app_data = await _execute(router, "POST", "/apps/app-1/enabled", {"enabled": True})
        assert toggled_app.ok and toggled_app_data == {
            "package": "app-1",
            "enabled": True,
            "requires_restart": True,
        }

        missing_ext = await router.route_text(
            RuntimeInput(
                text="/extensions/missing/enabled --enabled true",
                origin=InputOrigin.CONSOLE,
                session_id="s",
                source_app="t",
                source_instance="i",
            )
        )
        assert not missing_ext.ok and missing_ext.data is None

    asyncio.run(scenario())


def test_text_and_rest_share_parameters_and_envelope() -> None:
    async def scenario() -> None:
        runtime = _runtime()
        router = OperationRouter(runtime)
        engine = runtime.engine

        # REST 入口：路径参数
        rest, rest_data = await _execute(router, "GET", "/engine/tasks/t-1", {})
        assert rest.ok and rest_data == engine.task("t-1")

        # 文本入口：同一操作的 alias + positional 参数
        text = await router.route_text(
            RuntimeInput(
                text="/task t-1",
                origin=InputOrigin.CONSOLE,
                session_id="s",
                source_app="t",
                source_instance="i",
            )
        )
        assert text.ok and text.data == engine.task("t-1")

        # 文本入口：完整路径形态
        full = await router.route_text(
            RuntimeInput(
                text="/engine/tasks/t-1",
                origin=InputOrigin.CONSOLE,
                session_id="s",
                source_app="t",
                source_instance="i",
            )
        )
        assert full.ok and full.data == engine.task("t-1")

        # REST：GET query 参数（int 转换）
        tasks, tasks_data = await _execute(router, "GET", "/engine/tasks", {"limit": "10"})
        assert tasks.ok and isinstance(tasks_data["count"], int)

        # 文本：--key value 与 REST query 同构
        text_tasks = await router.route_text(
            RuntimeInput(
                text="/engine/tasks --limit 10",
                origin=InputOrigin.CONSOLE,
                session_id="s",
                source_app="t",
                source_instance="i",
            )
        )
        assert text_tasks.ok and text_tasks.data == tasks_data

        # POST：JSON body 与 REST 同构
        posted, posted_data = await _execute(router, "POST", "/messages", {"text": "hello"})
        assert posted.ok and posted_data["message_id"].startswith("conv:")

    asyncio.run(scenario())


def test_parameter_validation_and_error_codes() -> None:
    async def scenario() -> None:
        router = OperationRouter(_runtime())

        missing = await router.route_text(
            RuntimeInput(text="/task", origin=InputOrigin.CONSOLE, session_id="s", source_app="t", source_instance="i")
        )
        assert not missing.ok and missing.data is None
        assert missing.text is not None and "用法" in missing.text

        bad_type = await router.route_text(
            RuntimeInput(
                text="/engine/events --after_id not-an-int",
                origin=InputOrigin.CONSOLE,
                session_id="s",
                source_app="t",
                source_instance="i",
            )
        )
        assert not bad_type.ok and bad_type.data is None

        not_found = await router.route_text(
            RuntimeInput(
                text="/unknown-thing",
                origin=InputOrigin.CONSOLE,
                session_id="s",
                source_app="t",
                source_instance="i",
            )
        )
        assert not not_found.ok and not_found.data is None

        resolved, _, mismatch = router.resolve("DELETE", "/engine/tasks/t-1")
        assert resolved is None and mismatch is True

        unknown_path, _, mismatch_path = router.resolve("GET", "/no/such/resource")
        assert unknown_path is None and mismatch_path is False

    asyncio.run(scenario())


def test_help_flag_renders_usage_without_executing() -> None:
    async def scenario() -> None:
        runtime = _runtime()
        router = OperationRouter(runtime)

        long_help = await router.route_text(
            RuntimeInput(
                text="/task --help",
                origin=InputOrigin.CONSOLE,
                session_id="s",
                source_app="t",
                source_instance="i",
            )
        )
        assert long_help.ok
        assert "GET /engine/tasks/{task_id}" in (long_help.text or "")
        assert "别名: /task" in (long_help.text or "")

        short_help = await router.route_text(
            RuntimeInput(
                text="/engine/pump -h",
                origin=InputOrigin.CONSOLE,
                session_id="s",
                source_app="t",
                source_instance="i",
            )
        )
        assert short_help.ok
        assert "POST /engine/pump" in (short_help.text or "")
        assert "--max_turns" in (short_help.text or "")

        alias_help = await router.route_text(
            RuntimeInput(
                text="/say --help",
                origin=InputOrigin.CONSOLE,
                session_id="s",
                source_app="t",
                source_instance="i",
            )
        )
        assert alias_help.ok
        assert "POST /messages" in (alias_help.text or "")

    asyncio.run(scenario())


def test_short_flag_compacts_and_slices_output() -> None:
    async def scenario() -> None:
        router = OperationRouter(_runtime())

        async def route(text: str) -> CommandResult:
            return await router.route_text(
                RuntimeInput(
                    text=text,
                    origin=InputOrigin.CONSOLE,
                    session_id="s",
                    source_app="t",
                    source_instance="i",
                )
            )

        await route("/engine/tasks")
        compact = await route("/engine/tasks --short")
        assert compact.ok and compact.text is not None
        assert "\n" not in compact.text
        assert "t-1" in compact.text

        head = await route("/engine/tasks --short :50")
        assert head.ok and head.text == (compact.text or "")[:50]

        tail = await route("/engine/tasks --short=5:")
        assert tail.ok and tail.text == (compact.text or "")[5:]

        with_python_slice = await route("/engine/status --short 100:50")
        assert with_python_slice.ok and with_python_slice.text == ""

        invalid = await route("/engine/tasks --short 1x:2")
        assert invalid.ok and invalid.text == compact.text

        explicit = await route("/engine/tasks --short :50 --limit 1")
        assert explicit.ok
        assert explicit.text == (compact.text or "")[:50]

    asyncio.run(scenario())


def test_control_semantics_clear_and_shutdown() -> None:
    async def scenario() -> None:
        runtime = _runtime()
        router = OperationRouter(runtime)

        cleared = await router.route_text(
            RuntimeInput(text="/clear", origin=InputOrigin.CONSOLE, session_id="s", source_app="t", source_instance="i")
        )
        assert cleared.control is CommandControl.CLEAR_CONSOLE

        quitting = await router.route_text(
            RuntimeInput(text="/quit", origin=InputOrigin.CONSOLE, session_id="s", source_app="t", source_instance="i")
        )
        assert quitting.control is CommandControl.SHUTDOWN_PROCESS

    asyncio.run(scenario())


def test_domain_queries_memory_ai_config_prompt() -> None:
    async def scenario() -> None:
        router = OperationRouter(_runtime())

        memory, memory_data = await _execute(router, "GET", "/memory/history", {"scope": "s1"})
        assert memory.ok and memory_data["window"][0]["content"] == "hi"

        search, search_data = await _execute(router, "GET", "/memory/search", {"query": "fact"})
        assert search.ok and search_data["count"] == 1

        cost, cost_data = await _execute(router, "GET", "/ai/cost", {})
        assert cost.ok and cost_data["total_cost"] == 1.5

        roles, roles_data = await _execute(router, "GET", "/ai/roles", {})
        assert roles.ok and roles_data["count"] == 1

        profiles, profiles_data = await _execute(router, "GET", "/agents/profiles", {})
        assert profiles.ok and profiles_data["profiles"][0]["id"] == "root"

        prompt, prompt_data = await _execute(router, "GET", "/prompts/root", {})
        assert prompt.ok and prompt_data["text"] == "prompt:root"

        missing_prompt, _ = await _execute(router, "GET", "/prompts/missing", {})
        assert not missing_prompt.ok and missing_prompt.code == "NOT_FOUND"

        export, _ = await _execute(router, "GET", "/engine/sessions/s1/export", {})
        assert not export.ok and export.code == "NOT_FOUND"

        events, events_data = await _execute(router, "GET", "/engine/events", {})
        assert events.ok and events_data["count"] == 0

    asyncio.run(scenario())
