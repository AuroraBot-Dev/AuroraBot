"""大回执正文通过固定资源引用保存，世界台账保持紧凑。"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from aurorabot.contracts.artifact import ArtifactInfo, ArtifactIntegrityError
from aurorabot.contracts.artifact_codec import artifact_data, read_artifact
from aurorabot.contracts.resource import ResourceKey
from aurorabot.operations.codec import read_result, result_data
from aurorabot.operations.payloads import OperationPayloads

if TYPE_CHECKING:
    from collections.abc import Mapping

    from aurorabot.contracts.operation import OperationRequest, OperationResult
    from aurorabot.contracts.pkgs.artifacts import ArtifactStore

DEFAULT_INLINE_RECEIPT = 64 * 1024
_MEDIA_TYPE = "application/vnd.aurora.operation-result+json;version=1"
_REFERENCE_SCHEMA = 2


class OperationReceipts:
    """正文先发布、引用后提交；引用无法恢复时不允许重新执行效果。"""

    def __init__(self, artifacts: ArtifactStore | None, inline_bytes: int) -> None:
        """无内容存储的独立路由保留内联模式，正式装配总是注入存储。"""
        self._payloads = OperationPayloads(artifacts, inline_bytes)

    async def encode(
        self, request: OperationRequest, result: OperationResult
    ) -> tuple[Mapping[str, Any], ArtifactInfo | None]:
        """小回执沿用原格式，大回执只让紧凑描述进入世界日志。"""
        namespace = request.bot_id.split(":", maxsplit=1)[0]
        identity = request.identity.split(":", maxsplit=1)[1]
        key = ResourceKey(namespace, "operations", "result", identity)
        stored = await self._payloads.save(key, result_data(result), media_type=_MEDIA_TYPE)
        if isinstance(stored, ArtifactInfo):
            return {
                "schema_version": _REFERENCE_SCHEMA,
                "status": result.status.value,
                "result_ref": artifact_data(stored),
            }, stored
        return stored, None

    async def decode(self, data: Mapping[str, Any]) -> OperationResult:
        """恢复确切原结果；外部正文缺失不会覆盖已提交的执行状态。"""
        if "result_ref" not in data:
            return read_result(data)
        if data.get("schema_version") != _REFERENCE_SCHEMA:
            raise ArtifactIntegrityError("操作回执引用格式无法识别")
        try:
            info = read_artifact(data["result_ref"])
            result = read_result(await self._payloads.load(info, media_type=_MEDIA_TYPE))
        except (ValueError, TypeError, LookupError) as error:
            raise ArtifactIntegrityError("操作回执正文无法恢复") from error
        if result.status.value != data["status"]:
            raise ArtifactIntegrityError("操作回执正文与已提交的状态不一致")
        return replace(result, body_ref=info)
