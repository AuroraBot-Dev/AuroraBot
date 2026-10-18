"""资源内容能力经真实模组装配、操作路由和工具入口对外提供。"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import TYPE_CHECKING

import pytest
from test_assembly import FakeModel

from aurora import load_config
from aurora.configs.artifacts import CONFIG_SPEC
from src.artifacts.config import ArtifactsConfig
from src.contracts import ToolCall, ToolOutput
from src.contracts.artifact_codec import read_artifact
from src.contracts.operation import OperationKind, OperationRequest, OperationStatus
from src.contracts.pkgs.artifacts import ArtifactStore
from src.contracts.pkgs.operations import OperationRegistry
from src.contracts.pkgs.resources import ResourceCatalog
from src.contracts.pkgs.tools import ToolRegistry
from src.contracts.resource import ResourceKey, ResourceRef
from src.runtime import assemble_runtime
from src.utils.serialization import thaw_json

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

_KEY = "lab:memory/dataset/controlled-episodes"


def _request(action: str, arguments: Mapping[str, object], *, request_id: str = "request") -> OperationRequest:
    """构造与终端结构化调用相同的资源操作。"""
    kind = OperationKind.COMMAND if action == "put" else OperationKind.QUERY
    return OperationRequest(
        request_id,
        "aurora:bot/default",
        "test",
        ResourceRef(ResourceKey("aurora", "artifacts", kind.value, action), "1"),
        kind,
        arguments,
    )


def test_resource_content_is_available_through_port_registry_and_model_tools(configured_project: Path) -> None:
    """宿主和 Bot 共用固定资源版本，读写入口不会各建一套内容。"""
    config = load_config(configured_project)
    assert config.get(CONFIG_SPEC) == ArtifactsConfig()
    runtime = assemble_runtime(config, FakeModel(), output=lambda _: None)

    async def scenario() -> None:
        try:
            operations = runtime.assembly.get(OperationRegistry)
            content = "同一段经历与它的证据".encode()
            write = _request("put", {"key": _KEY, "content_base64": base64.b64encode(content).decode("ascii")})
            result = await operations.dispatch(write)
            assert result.status is OperationStatus.SUCCEEDED
            info = read_artifact(result.data)
            assert await runtime.assembly.get(ArtifactStore).stat(info.ref) == info
            assert await operations.dispatch(write) == result
            resources = runtime.assembly.get(ResourceCatalog)
            assert resources.resolve(write.target).ref == write.target
            tools = runtime.assembly.get(ToolRegistry)
            arguments = {"key": _KEY, "revision": info.ref.revision}
            stat = await operations.dispatch(_request("stat", arguments, request_id="stat"))
            assert stat.data == result.data
            output = await tools.execute(
                ToolCall("chunk", "aurora:tool/artifact_read", {**arguments, "offset": 1, "limit": 7})
            )
            assert isinstance(output, ToolOutput)
            body = json.loads(output.content)
            assert base64.b64decode(body["content_base64"]) == content[1:8]
            assert body["has_more"]
            assert body["next_offset"] == body["offset"] + len(base64.b64decode(body["content_base64"]))
            assert not output.evidence_refs
            assert "aurora:tool/artifact_put" not in tools.names
        finally:
            await runtime.world.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "action,arguments",
    [
        ("put", {"key": _KEY, "content_base64": "not base64"}),
        ("put", {"key": "bad", "content_base64": "YQ=="}),
        ("read", {"key": _KEY, "revision": "a" * 64, "limit": 16385}),
        ("stat", {"key": _KEY, "revision": "latest"}),
        ("stat", {"key": _KEY, "revision": "a" * 64}),
    ],
)
def test_invalid_resource_calls_fail_without_publishing_content(
    configured_project: Path, action: str, arguments: dict[str, object]
) -> None:
    """编码、身份、版本和分块边界由公共入口真实校验。"""
    runtime = assemble_runtime(load_config(configured_project), FakeModel(), output=lambda _: None)

    async def scenario() -> None:
        try:
            result = await runtime.assembly.get(OperationRegistry).dispatch(_request(action, arguments))
            assert result.status is not OperationStatus.SUCCEEDED
            assert result.message
            assert not (configured_project / "data/artifacts/bindings").exists()
        finally:
            await runtime.world.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("directory", ["../outside", "/absolute", "C:/outside", ""])
def test_resource_config_requires_a_project_relative_directory(directory: str) -> None:
    """资源持久目录不能由配置中的绝对路径隐式改变。"""
    with pytest.raises(ValueError, match="项目内相对目录"):
        ArtifactsConfig(directory)


def test_large_content_upload_keeps_real_runtime_world_records_compact(configured_project: Path) -> None:
    """大内容上传本身不能通过请求日志把 base64 正文再次带回世界索引。"""
    runtime = assemble_runtime(load_config(configured_project), FakeModel(), output=lambda _: None)

    async def scenario() -> None:
        try:
            content = "连续训练经历".encode() * 10000
            request = _request("put", {"key": _KEY, "content_base64": base64.b64encode(content).decode("ascii")})
            operations = runtime.assembly.get(OperationRegistry)
            result = await operations.dispatch(request)
            assert result.status is OperationStatus.SUCCEEDED
            info = read_artifact(result.data)
            page = await runtime.world.stream(0, 10)
            request_fact = next(commit for commit in page.commits if commit.kind == "operation.requested")
            assert "request_ref" in request_fact.data["request"]
            assert all("content_base64" not in json.dumps(thaw_json(commit.data)) for commit in page.commits)
            assert await operations.dispatch(request) == result
            stored = await runtime.assembly.get(ArtifactStore).read(info.ref, limit=info.size)
            assert stored.content == content
        finally:
            await runtime.world.close()

    asyncio.run(scenario())


def test_strict_resource_input_reports_a_chinese_error(configured_project: Path) -> None:
    """JSON Schema 允许整数形式的浮点数时，严格输入模型仍返回可理解的中文失败原因。"""
    runtime = assemble_runtime(load_config(configured_project), FakeModel(), output=lambda _: None)

    async def scenario() -> None:
        try:
            request = _request("read", {"key": _KEY, "revision": "a" * 64, "limit": 1.0})
            result = await runtime.assembly.get(OperationRegistry).dispatch(request)
            assert result.status is OperationStatus.FAILED
            assert result.message == "资源参数不符合声明结构"
        finally:
            await runtime.world.close()

    asyncio.run(scenario())
