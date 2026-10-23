"""将已发布内容的有界发现提供给 Bot 与终端调用。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from aurora_bot.contracts import ToolScopes
from aurora_bot.contracts.artifact_codec import artifact_data
from aurora_bot.contracts.operation import OperationDefinition, OperationResult, OperationStatus
from aurora_bot.contracts.resource import ResourceKey, ResourceRef
from aurora_bot.contracts.resource_requests import ResourceQueryInput
from aurora_bot.utils.serialization import thaw_json

if TYPE_CHECKING:
    from aurora_bot.contracts.operation import OperationRequest
    from aurora_bot.contracts.pkgs.artifacts import ArtifactStore


class ArtifactFindOperation:
    """发现不会载入正文，读取固定版本需继续调用 stat 或 read。"""

    definition = OperationDefinition(
        ResourceRef(ResourceKey("aurora", "artifacts", "query", "find"), "1"),
        "分页发现已发布的数据集、模型和其他内容版本。items 只含清单元信息，content_verified=false。"
        "使用 next_cursor 作为 after 继续，保持筛选不变；这是当前目录的动态列表，新增内容可能需要重新发现。"
        "取得 key 与 revision 后，用 artifact_stat 核对完整性或 artifact_read 读取正文。",
        ResourceQueryInput.model_json_schema(),
        "aurora:tool/definition/artifact_find",
        True,
    )

    def __init__(self, store: ArtifactStore) -> None:
        """参数结构与工具帮助均从同一输入模型产生。"""
        self._store = store

    def scopes_for(self, request: OperationRequest) -> ToolScopes:
        """内容清单不产生新的业务世界域。"""
        return ToolScopes()

    async def execute(self, request: OperationRequest) -> OperationResult:
        """查询参数和游标有误时明确失败，不能悄悄变更筛选。"""
        try:
            inputs = ResourceQueryInput.model_validate(thaw_json(request.arguments))
            page = await self._store.find(inputs.query)
            return OperationResult(
                {
                    "items": [artifact_data(info) for info in page.items],
                    "next_cursor": page.next_cursor,
                    "listing_mode": "live",
                    "content_verified": False,
                }
            )
        except ValidationError:
            return OperationResult(status=OperationStatus.FAILED, message="资源发现参数不符合声明结构")
        except (ValueError, LookupError) as error:
            return OperationResult(status=OperationStatus.FAILED, message=str(error))
