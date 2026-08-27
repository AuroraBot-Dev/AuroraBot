"""组合 ops 端口、操作注册表与双入口路由。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ops.contracts import OperationResult, OperationSpec, OpsPorts
from ops.registry import catalog_entries
from ops.router import OperationRouter

if TYPE_CHECKING:
    from ops.contracts import (
        AgentsRuntimePort,
        AiRuntimePort,
        CadenceRuntimePort,
        ConfigReloadPort,
        ConfigRuntimePort,
        ConsoleRuntimePort,
        ContractsRuntimePort,
        McpRuntimePort,
        MemoryRuntimePort,
        ProcessRuntimePort,
        PromptRuntimePort,
        ToolsRuntimePort,
        TreeRuntimePort,
        UtilsRuntimePort,
        WorldRuntimePort,
    )


class OpsRuntime:
    """热路径外的统一操作运行时。"""

    def __init__(
        self,
        engine: TreeRuntimePort,
        config: ConfigRuntimePort,
        process: ProcessRuntimePort,
        *,
        agents: AgentsRuntimePort | None = None,
        tools: ToolsRuntimePort | None = None,
        prompt: PromptRuntimePort | None = None,
        ai: AiRuntimePort | None = None,
        world: WorldRuntimePort | None = None,
        console: ConsoleRuntimePort | None = None,
        utils: UtilsRuntimePort | None = None,
        contracts: ContractsRuntimePort | None = None,
        cadence: CadenceRuntimePort | None = None,
        memory: MemoryRuntimePort | None = None,
        mcp: McpRuntimePort | None = None,
        config_reload: ConfigReloadPort | None = None,
    ) -> None:
        self._router = OperationRouter(
            OpsPorts(
                engine,
                config,
                process,
                agents,
                tools,
                prompt,
                ai,
                world,
                console,
                utils,
                contracts,
                cadence,
                memory,
                mcp,
                config_reload,
            )
        )

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
