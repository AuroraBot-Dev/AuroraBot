"""操作身份、调用语义与不可变参数的协议测试。"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from aurorabot.contracts.operation import (
    OperationDefinition,
    OperationKind,
    OperationRequest,
    OperationResult,
    OperationStatus,
)
from aurorabot.contracts.resource import ResourceKey, ResourceRef

_REF = ResourceRef(ResourceKey.parse("aurora:bot/command/goal_set"), "1")


def test_definition_drives_resource_metadata_and_call_semantics() -> None:
    """资源种类唯一决定调用语义，工具只是一个可选入口。"""
    definition = OperationDefinition(
        _REF, "选择目标", {"type": "object"}, "aurora:tool/definition/goal_set", retry_safe=True
    )
    assert definition.kind is OperationKind.COMMAND
    assert definition.resource.ref == _REF
    assert definition.resource.metadata["retry_safe"] is True


def test_request_copies_parameters_and_keeps_causality_separate() -> None:
    """外部修改不能改变已登记请求，关联和因果分别保留。"""
    arguments = {"items": ["first"]}
    request = OperationRequest(
        "request-1", "aurora:bot/test", "test", _REF, OperationKind.COMMAND, arguments, "conversation", "world:1"
    )
    arguments["items"].append("second")
    assert request.arguments["items"] == ("first",)
    assert request.correlation_id == "conversation"
    assert request.caused_by == "world:1"


def test_unknown_and_failed_results_require_explanation() -> None:
    """结果未知与执行失败不能用空回执冒充成功。"""
    with pytest.raises(ValueError, match="原因"):
        OperationResult(status=OperationStatus.UNKNOWN)
    with pytest.raises(ValueError, match="原因"):
        OperationResult(status=OperationStatus.FAILED, message=" ")
    assert OperationResult({"answer": 1}).status is OperationStatus.SUCCEEDED


def test_protocol_rejects_unversioned_definitions_and_naive_deadlines() -> None:
    """调用结构必须具备确定版本和无歧义时间。"""
    with pytest.raises(ValueError, match="确定版本"):
        OperationDefinition(ResourceRef(_REF.key), "选择目标", {})
    request = OperationRequest("request", "aurora:bot/test", "test", _REF, OperationKind.COMMAND)
    with pytest.raises(ValueError, match="时区"):
        replace(request, deadline_at=datetime(2026, 10, 18, tzinfo=UTC).replace(tzinfo=None))
    with pytest.raises(ValueError, match="Bot"):
        replace(request, bot_id="aurora:agent/definition/root")
