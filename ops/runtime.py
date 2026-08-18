"""组合 ops 端口、操作注册表与双入口路由。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ops.contracts import OperationResult, OpsPorts
from ops.registry import catalog_entries
from ops.router import OperationRouter

if TYPE_CHECKING:
    from ops.contracts import ConfigRuntimePort, TreeRuntimePort


class OpsRuntime:
    """热路径外的统一操作运行时。"""

    def __init__(self, engine: TreeRuntimePort, config: ConfigRuntimePort) -> None:
        self._router = OperationRouter(OpsPorts(engine, config))

    @property
    def catalog(self) -> list[dict[str, Any]]:
        return catalog_entries()

    async def execute(self, method: str, path: str, params: dict[str, Any] | None = None) -> OperationResult:
        return await self._router.execute_path(method, path, params)

    async def route_text(self, raw: str) -> OperationResult:
        return await self._router.route_text(raw)
