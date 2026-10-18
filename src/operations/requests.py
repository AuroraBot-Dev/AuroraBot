"""在执行前固定完整请求，大参数通过不可变资源进入世界。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from src.contracts.artifact import ArtifactInfo, ArtifactIntegrityError
from src.contracts.artifact_codec import artifact_data, read_artifact
from src.contracts.data import freeze_object
from src.contracts.resource import ResourceKey
from src.operations.codec import request_data
from src.operations.payloads import OperationPayloads

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.contracts.operation import OperationRequest
    from src.contracts.pkgs.artifacts import ArtifactStore

DEFAULT_INLINE_REQUEST = 64 * 1024
_MEDIA_TYPE = "application/vnd.aurora.operation-request+json;version=1"
_REFERENCE_SCHEMA = 2


class OperationRequests:
    """请求正文失踪时拒绝恢复，不猜测原参数或复用调用方的替代内容。"""

    def __init__(self, artifacts: ArtifactStore | None, inline_bytes: int) -> None:
        """请求和回执共用存储，但使用不同逻辑名称和内容类型。"""
        self._payloads = OperationPayloads(artifacts, inline_bytes)

    async def encode(self, request: OperationRequest) -> Mapping[str, Any]:
        """大请求先发布完整正文，成功后才能登记请求并进入处理者。"""
        namespace = request.bot_id.split(":", maxsplit=1)[0]
        identity = request.identity.split(":", maxsplit=1)[1]
        key = ResourceKey(namespace, "operations", "request", identity)
        stored = await self._payloads.save(key, request_data(request), media_type=_MEDIA_TYPE)
        if isinstance(stored, ArtifactInfo):
            return {"schema_version": _REFERENCE_SCHEMA, "request_ref": artifact_data(stored)}
        return stored

    async def decode(self, data: Mapping[str, Any]) -> Mapping[str, Any]:
        """只返回原请求，用于恢复前逐字段核对同一身份的真实意图。"""
        if "request_ref" not in data:
            return await asyncio.to_thread(freeze_object, data)
        if data.get("schema_version") != _REFERENCE_SCHEMA:
            raise ArtifactIntegrityError("操作请求引用格式无法识别")
        try:
            info = read_artifact(data["request_ref"])
            return await self._payloads.load(info, media_type=_MEDIA_TYPE)
        except (ValueError, TypeError, LookupError) as error:
            raise ArtifactIntegrityError("操作请求正文无法恢复") from error
