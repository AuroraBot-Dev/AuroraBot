"""大回执正文通过固定资源引用保存，世界台账保持紧凑。"""

from __future__ import annotations

import json
from dataclasses import replace
from itertools import chain
from typing import TYPE_CHECKING, Any

from src.contracts.artifact import MAX_ARTIFACT_CHUNK, ArtifactIntegrityError
from src.contracts.artifact_codec import artifact_data, read_artifact
from src.contracts.resource import ResourceKey
from src.operations.codec import read_result, result_data
from src.utils.json_stream import json_bytes

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.contracts.artifact import ArtifactInfo
    from src.contracts.operation import OperationRequest, OperationResult
    from src.contracts.pkgs.artifacts import ArtifactStore

DEFAULT_INLINE_RECEIPT = 64 * 1024
_MEDIA_TYPE = "application/vnd.aurora.operation-result+json;version=1"
_REFERENCE_SCHEMA = 2


class OperationReceipts:
    """正文先发布、引用后提交；引用无法恢复时不允许重新执行效果。"""

    def __init__(self, artifacts: ArtifactStore | None, inline_bytes: int) -> None:
        """无内容存储的独立路由保留内联模式，正式装配总是注入存储。"""
        if type(inline_bytes) is not int or inline_bytes <= 0:
            raise ValueError("回执内联上限必须是正整数字节数")
        self._artifacts = artifacts
        self._inline_bytes = inline_bytes

    async def encode(
        self, request: OperationRequest, result: OperationResult
    ) -> tuple[Mapping[str, Any], ArtifactInfo | None]:
        """小回执沿用原格式，大回执只让紧凑描述进入世界日志。"""
        payload = result_data(result)
        if self._artifacts is None:
            return payload, None
        chunks = json_bytes(payload)
        prefix = bytearray()
        for chunk in chunks:
            if len(prefix) + len(chunk) > self._inline_bytes:
                namespace = request.bot_id.split(":", maxsplit=1)[0]
                identity = request.identity.split(":", maxsplit=1)[1]
                key = ResourceKey(namespace, "operations", "result", identity)
                info = await self._artifacts.put_stream(
                    key, chain((bytes(prefix), chunk), chunks), media_type=_MEDIA_TYPE
                )
                return {
                    "schema_version": _REFERENCE_SCHEMA,
                    "status": result.status.value,
                    "result_ref": artifact_data(info),
                }, info
            prefix.extend(chunk)
        return json.loads(prefix), None

    async def decode(self, data: Mapping[str, Any]) -> OperationResult:
        """恢复确切原结果；外部正文缺失不会覆盖已提交的执行状态。"""
        if "result_ref" not in data:
            return read_result(data)
        if data.get("schema_version") != _REFERENCE_SCHEMA:
            raise ArtifactIntegrityError("操作回执引用格式无法识别")
        if self._artifacts is None:
            raise ArtifactIntegrityError("操作回执正文已保存为资源，但当前没有装配内容存储")
        info = read_artifact(data["result_ref"])
        if info.media_type != _MEDIA_TYPE:
            raise ArtifactIntegrityError("操作回执资源的媒体类型不匹配")
        payload = await self._read(info)
        try:
            result = read_result(json.loads(payload))
        except (ValueError, TypeError, KeyError) as error:
            raise ArtifactIntegrityError("操作回执正文格式已损坏") from error
        if result.status.value != data["status"]:
            raise ArtifactIntegrityError("操作回执正文与已提交的状态不一致")
        return replace(result, body_ref=info)

    async def _read(self, info: ArtifactInfo) -> bytearray:
        """只有显式恢复回执时才读取完整正文，不把它加入全局投影。"""
        if self._artifacts is None:
            raise ArtifactIntegrityError("未装配操作回执内容存储")
        payload = bytearray()
        while len(payload) < info.size:
            chunk = await self._artifacts.read(info.ref, offset=len(payload), limit=MAX_ARTIFACT_CHUNK)
            if chunk.info != info or chunk.offset != len(payload) or not chunk.content:
                raise ArtifactIntegrityError("操作回执分块与已提交描述不一致")
            payload.extend(chunk.content)
        return payload
