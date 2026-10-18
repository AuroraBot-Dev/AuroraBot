"""操作请求和执行回执的持久格式。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.contracts.operation import OperationResult, OperationStatus
from src.contracts.resource import ResourceKey, ResourceRef
from src.utils.serialization import thaw_json

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.contracts.operation import OperationRequest


def reference_data(ref: ResourceRef) -> dict[str, Any]:
    """分别记录资源身份和确定版本。"""
    return {"key": str(ref.key), "revision": ref.revision}


def read_reference(data: Mapping[str, Any]) -> ResourceRef:
    """从回执中恢复已冻结的调用目标。"""
    return ResourceRef(ResourceKey.parse(data["key"]), data["revision"])


def request_data(request: OperationRequest) -> dict[str, Any]:
    """编码入口身份、关联关系、期限与参数。"""
    return {
        "schema_version": 1,
        "request_id": request.request_id,
        "bot_id": request.bot_id,
        "source": request.source,
        "target": reference_data(request.target),
        "kind": request.kind.value,
        "arguments": thaw_json(request.arguments),
        "correlation_id": request.correlation_id,
        "caused_by": request.caused_by,
        "deadline_at": request.deadline_at.isoformat() if request.deadline_at is not None else None,
    }


def result_data(result: OperationResult) -> dict[str, Any]:
    """保留结果状态与可读取的结构化正文。"""
    return {
        "status": result.status.value,
        "data": result.data,
        "message": result.message,
        "evidence_refs": list(result.evidence_refs),
    }


def read_result(data: Mapping[str, Any]) -> OperationResult:
    """恢复一次已经持久确认的调用结果。"""
    return OperationResult(
        data["data"], OperationStatus(data["status"]), data["message"], tuple(data.get("evidence_refs", ()))
    )
