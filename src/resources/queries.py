"""Bot 与终端共用的资源发现和指定版本检查操作。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from src.contracts import ToolScopes
from src.contracts.operation import OperationDefinition, OperationResult, OperationStatus
from src.contracts.resource_codec import resource_data, resource_page_data
from src.contracts.resource_requests import RESOURCE_FIND, RESOURCE_INSPECT, ResourceInspectInput, ResourceQueryInput
from src.utils.serialization import thaw_json

if TYPE_CHECKING:
    from src.contracts.operation import OperationRequest
    from src.contracts.pkgs.resources import ResourceCatalog


class ResourceFindQuery:
    """按需发现当前能力、模型和数据集，不把所有说明一次注入上下文。"""

    definition = OperationDefinition(
        RESOURCE_FIND,
        "按命名空间、领域和类别分页发现资源定义、已发布内容与认知实例。"
        "使用 next_cursor 作为 after 继续，保持筛选条件不变；当前动态列表中的新增内容可能需要重新发现。"
        "内容清单不表示正文已读，使用 resources_inspect 检查指定版本。",
        ResourceQueryInput.model_json_schema(),
        "aurora:tool/definition/resources_find",
        True,
    )

    def __init__(self, catalog: ResourceCatalog) -> None:
        """使用装配选中的同一资源目录。"""
        self._catalog = catalog

    def scopes_for(self, request: OperationRequest) -> ToolScopes:
        """资源来源自行持有数据，发现不生成新的业务世界域。"""
        return ToolScopes()

    async def execute(self, request: OperationRequest) -> OperationResult:
        """跨来源的校验失败不能伪装成完整的空结果。"""
        try:
            inputs = ResourceQueryInput.model_validate(thaw_json(request.arguments))
            return OperationResult(resource_page_data(await self._catalog.browse(inputs.query)))
        except ValidationError:
            return OperationResult(status=OperationStatus.FAILED, message="资源发现参数不符合声明结构")
        except (ValueError, LookupError) as error:
            return OperationResult(status=OperationStatus.FAILED, message=str(error))


class ResourceInspectQuery:
    """检查一项定义或确定内容版本，发现说明与实际正文仍保持区分。"""

    definition = OperationDefinition(
        RESOURCE_INSPECT,
        "读取资源说明、参数结构与能力契约。静态定义可省略唯一版本或使用显式别名；动态内容与实例状态必须指定 revision。"
        "检查内容版本会核对完整性；正文通过其 read_operation 按块读取。实例检查按指定版本重建世界记录摘要。",
        ResourceInspectInput.model_json_schema(),
        "aurora:tool/definition/resources_inspect",
        True,
    )

    def __init__(self, catalog: ResourceCatalog) -> None:
        """检查与发现共享目录和实际提供者。"""
        self._catalog = catalog

    def scopes_for(self, request: OperationRequest) -> ToolScopes:
        """读取的是资源描述，不取得正文来源的证据归属。"""
        return ToolScopes()

    async def execute(self, request: OperationRequest) -> OperationResult:
        """缺失、契约不匹配和内容损坏均作为明确失败返回。"""
        try:
            inputs = ResourceInspectInput.model_validate(thaw_json(request.arguments))
            descriptor = await self._catalog.inspect(inputs.ref, contract=inputs.required_contract)
            return OperationResult(resource_data(descriptor))
        except ValidationError:
            return OperationResult(status=OperationStatus.FAILED, message="资源检查参数不符合声明结构")
        except (ValueError, LookupError) as error:
            return OperationResult(status=OperationStatus.FAILED, message=str(error))
