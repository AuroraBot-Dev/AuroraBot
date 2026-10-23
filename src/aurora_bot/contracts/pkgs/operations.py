"""领域操作的统一发现与执行端口。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from aurora_bot.contracts.operation import OperationDefinition, OperationRequest, OperationResult
    from aurora_bot.contracts.resource import ResourceRef
    from aurora_bot.contracts.world import ToolScopes


class OperationRegistry(Protocol):
    """绑定资源版本并执行调用，不依赖模组实现。"""

    @property
    def definitions(self) -> tuple[OperationDefinition, ...]:
        """返回具有确定版本的可调用能力。"""
        ...

    def definition(self, ref: ResourceRef) -> OperationDefinition:
        """解析别名或版本，取得相应调用定义。"""
        ...

    def scopes_for(self, request: OperationRequest) -> ToolScopes:
        """返回路由目标要求的观察与发布域。"""
        ...

    async def dispatch(self, request: OperationRequest) -> OperationResult:
        """统一校验、记录并执行命令或查询。"""
        ...
