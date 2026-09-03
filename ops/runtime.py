"""组合 ops 端口、操作注册表与双入口路由。

OpsRuntime 直接持有唯一的 AuroraAssembly 与进程面协议对象：实例化窄端口由
ops.ports 从 assembly 派生，aurora 不再把适配器装配进 ops。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ops.ports import build_ops_ports
from ops.registry import catalog_entries
from ops.router import OperationRouter

if TYPE_CHECKING:
    from aurora.composer import AuroraAssembly
    from ops.contracts import OperationResult, OperationSpec, OpsPorts


class OpsRuntime:
    """热路径外的统一操作运行时。"""

    def __init__(self, assembly: AuroraAssembly, process: object) -> None:
        self._assembly = assembly
        self._ports = build_ops_ports(assembly, process, process, process)
        self._router = OperationRouter(self._ports)

    @property
    def assembly(self) -> AuroraAssembly:
        return self._assembly

    @property
    def ports(self) -> OpsPorts:
        return self._ports

    @property
    def catalog(self) -> list[dict[str, Any]]:
        return catalog_entries()

    async def execute(self, method: str, path: str, params: dict[str, Any] | None = None) -> OperationResult:
        return await self._router.execute_path(method, path, params)

    def resolve(self, method: str, path: str) -> tuple[OperationSpec | None, dict[str, str] | None, bool]:
        return self._router.resolve(method, path)

    async def execute_resolved(self, spec: OperationSpec, params: dict[str, Any]) -> OperationResult:
        return await self._router.execute_resolved(spec, params)

    async def route_text(self, raw: str) -> OperationResult:
        return await self._router.route_text(raw)
