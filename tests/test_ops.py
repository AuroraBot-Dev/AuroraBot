from __future__ import annotations

import asyncio
import tomllib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest

from aurora import assemble_runtime, load_config
from ops import ConfigAccess, ConfigSourceRef
from ops.contracts import OperationResult, OpsPorts
from ops.parser import CommandParseError, coerce_value, split_text
from ops.registry import iter_operations
from ops.router import OperationRouter, render_result
from src.contracts import ChatMessage, ModelRequest

if TYPE_CHECKING:
    from pathlib import Path

_MIN_OPERATION_COUNT = 9


@dataclass(slots=True)
class FakeModel:
    responses: list[str] = field(default_factory=lambda: ["完成"])

    async def complete(self, request: ModelRequest) -> ChatMessage:
        _ = request
        return ChatMessage.assistant(self.responses.pop(0))


class FakeTrees:
    async def start_tree(self, message: str, *, tree_id: str | None = None) -> dict[str, Any]:
        return {"tree_id": tree_id or "generated", "message": message}

    def runtime_status(self) -> dict[str, Any]:
        return {"tree_count": 1}

    def list_trees(self, *, status: str | None = None, limit: int = 64) -> list[dict[str, Any]]:
        return [{"tree_id": "tree", "status": status, "limit": limit}]

    def tree_detail(self, tree_id: str) -> dict[str, Any] | None:
        return {"tree_id": tree_id} if tree_id == "tree" else None

    def node_detail(self, tree_id: str, node_id: str) -> dict[str, Any] | None:
        return {"tree_id": tree_id, "node_id": node_id} if node_id == "root" else None


class FakeConfig:
    def snapshot(self) -> dict[str, Any]:
        return {"sources": []}

    def read(self, name: str) -> dict[str, Any] | None:
        return {"name": name} if name == "runtime" else None

    def set_app_enabled(self, package: str, *, enabled: bool) -> dict[str, Any]:
        if package == "missing":
            raise KeyError(package)
        return {"package": package, "enabled": enabled}

    def set_extension_enabled(self, extension_id: str, *, enabled: bool) -> dict[str, Any]:
        if extension_id == "missing":
            raise ValueError(extension_id)
        return {"id": extension_id, "enabled": enabled}


def _router() -> OperationRouter:
    return OperationRouter(OpsPorts(FakeTrees(), FakeConfig()))


def test_operation_catalog_and_method_path_router_share_registered_specs() -> None:
    specs = iter_operations()
    router = _router()

    catalog = asyncio.run(router.execute_path("GET", "/"))
    status = asyncio.run(router.execute_path("GET", "/engine/status"))
    mismatch = asyncio.run(router.execute_path("DELETE", "/trees"))
    missing = asyncio.run(router.execute_path("GET", "/missing"))

    assert len(specs) >= _MIN_OPERATION_COUNT
    assert catalog.ok is True
    assert len(catalog.data["operations"]) == len(specs)  # type: ignore[index]
    assert status.data == {"tree_count": 1}
    assert mismatch.code == "METHOD_NOT_ALLOWED"
    assert missing.code == "NOT_FOUND"


def test_text_router_supports_aliases_paths_named_values_and_help() -> None:
    router = _router()

    started = asyncio.run(router.route_text('/run "请完成任务" --tree_id tree-2'))
    tree = asyncio.run(router.route_text("/trees/tree"))
    node = asyncio.run(router.route_text("/trees/tree/nodes/root"))
    listed = asyncio.run(router.execute_path("GET", "/trees", {"status": "completed", "limit": "2"}))
    help_result = asyncio.run(router.route_text("/run --help"))
    unknown = asyncio.run(router.route_text("/unknown"))
    invalid = asyncio.run(router.route_text("run without slash"))

    assert started.data == {"tree_id": "tree-2", "message": "请完成任务"}
    assert tree.data == {"tree_id": "tree"}
    assert node.data == {"tree_id": "tree", "node_id": "root"}
    assert listed.data == {"trees": [{"tree_id": "tree", "status": "completed", "limit": 2}]}
    assert help_result.message is not None
    assert "用法" not in help_result.message
    assert "POST /trees" in help_result.message
    assert unknown.code == "NOT_FOUND"
    assert invalid.code == "PARSE_ERROR"


def test_router_returns_parse_and_operation_errors_in_chinese() -> None:
    router = _router()

    missing_message = asyncio.run(router.route_text("/run"))
    bad_limit = asyncio.run(router.execute_path("GET", "/trees", {"limit": 0}))
    absent_tree = asyncio.run(router.execute_path("GET", "/trees/absent"))
    absent_node = asyncio.run(router.execute_path("GET", "/trees/tree/nodes/absent"))
    absent_config = asyncio.run(router.route_text("/config-show absent"))
    absent_app = asyncio.run(router.route_text("/app-enable missing true"))
    absent_extension = asyncio.run(router.route_text("/extension-enable missing true"))

    assert missing_message.code == "PARSE_ERROR"
    assert missing_message.message is not None
    assert "缺少必填参数" in missing_message.message
    assert bad_limit.code == "INVALID_LIMIT"
    assert absent_tree.code == absent_node.code == absent_config.code == "NOT_FOUND"
    assert absent_app.code == absent_extension.code == "CONFIG_ERROR"


def test_config_access_reads_registered_personal_files_and_preserves_comments(configured_project: Path) -> None:
    configuration = load_config(configured_project)
    sources = tuple(ConfigSourceRef(source.name, source.relative_path) for source in configuration.sources)
    access = ConfigAccess(configured_project, sources)
    app_path = configured_project / "config" / "apps.toml"
    extension_path = configured_project / "config" / "extensions.toml"

    app_result = access.set_app_enabled("org.aurora.clock", enabled=True)
    unchanged = access.set_app_enabled("org.aurora.clock", enabled=True)
    extension_result = access.set_extension_enabled("aurora.builtin.control", enabled=False)

    assert access.read("apps")["name"] == "apps"  # type: ignore[index]
    assert access.read("absent") is None
    assert app_result["changed"] is True and app_result["restart_required"] is True
    assert unchanged["changed"] is False and unchanged["restart_required"] is False
    assert extension_result["changed"] is True
    assert "# 内建 Clock 应用" in app_path.read_text(encoding="utf-8")
    assert "# 认知控制" in extension_path.read_text(encoding="utf-8")
    with app_path.open("rb") as stream:
        assert tomllib.load(stream)["app"][0]["enabled"] is True
    with extension_path.open("rb") as stream:
        assert tomllib.load(stream)["extension"][0]["enabled"] is False


def test_config_access_rejects_templates_and_unknown_entries(configured_project: Path) -> None:
    with pytest.raises(ValueError, match="个人 config"):
        ConfigAccess(configured_project, (ConfigSourceRef("template", "config.example/apps.toml"),))

    access = ConfigAccess(configured_project, (ConfigSourceRef("apps", "config/apps.toml"),))
    with pytest.raises(KeyError, match="配置尚未注册"):
        access.set_extension_enabled("anything", enabled=True)
    with pytest.raises(KeyError, match="不存在"):
        access.set_app_enabled("missing", enabled=True)


def test_config_access_rejects_personal_directory_symlink(tmp_path: Path) -> None:
    template = tmp_path / "config.example"
    template.mkdir()
    (template / "apps.toml").write_text("app = []\n", encoding="utf-8")
    (tmp_path / "config").symlink_to(template, target_is_directory=True)

    with pytest.raises(ValueError, match="符号链接"):
        ConfigAccess(tmp_path, (ConfigSourceRef("apps", "config/apps.toml"),))


def test_assembled_runtime_exposes_live_tree_snapshots_and_ops(configured_project: Path) -> None:
    runtime = assemble_runtime(load_config(configured_project), FakeModel())

    initial = asyncio.run(runtime.ops.execute("GET", "/engine/status"))
    result = asyncio.run(runtime.run("你好", tree_id="tree-live"))
    listed = asyncio.run(runtime.ops.route_text("/trees"))
    detail = asyncio.run(runtime.ops.execute("GET", "/trees/tree-live"))
    node = asyncio.run(runtime.ops.execute("GET", f"/trees/tree-live/nodes/{result.root_id}"))

    assert initial.data["tree_count"] == 0  # type: ignore[index]
    assert listed.data["trees"][0]["status"] == "completed"  # type: ignore[index]
    assert detail.data["nodes"][0]["messages"][-1]["role"] == "assistant"  # type: ignore[index]
    assert node.data["model"] == runtime.root.model  # type: ignore[index]
    with pytest.raises(ValueError, match="已存在"):
        asyncio.run(runtime.run("重复", tree_id="tree-live"))


def test_parser_and_renderer_cover_invalid_shell_and_scalar_types() -> None:
    specs = {spec.name: spec for spec in iter_operations()}
    enabled = specs["config.app_enabled"].parameter("enabled")
    assert enabled is not None
    assert split_text('/run "hello world"') == ("/run", "hello world")
    assert coerce_value("yes", enabled) is True
    assert coerce_value("no", enabled) is False
    with pytest.raises(CommandParseError, match="需要 bool"):
        coerce_value("sometimes", enabled)
    with pytest.raises(CommandParseError):
        split_text('/run "unfinished')
    assert "完成" in render_result(OperationResult.success(message="完成"))
    assert '"value": 1' in render_result(OperationResult.success({"value": 1}))
    assert render_result(OperationResult.failure("FAILED", "")) == ""
