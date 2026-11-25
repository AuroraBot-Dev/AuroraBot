"""独立 MCP 客户端所有者；SDK 上下文始终由同一任务进入和退出。"""

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from aurora_core import entry_from, hook_handler
from aurora_core.ctx import Context
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import CLEAN, CONFIG, PREPARE, STOP, LifecycleComponent
from mcp import Client

from . import transports
from .configuration import (
    CAPABILITIES,
    CLIENT_STATUS,
    CONFIG_STATE,
    MCP_CONFIG,
    configured_servers,
)
from .errors import MCPClientError, error_code
from .negotiation import Negotiation


@dataclass
class _Connection:
    config: dict
    negotiation: Negotiation
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    close: asyncio.Event = field(default_factory=asyncio.Event)
    idle: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None
    client: Client | None = None
    users: dict[asyncio.Task, int] = field(default_factory=dict)
    cancelled_users: set[asyncio.Task] = field(default_factory=set)
    cancel_requested: bool = False
    phase: str = "configured"
    error: str | None = None
    error_location: str | None = None
    capabilities: list[str] = field(default_factory=list)


class MCPClients:
    """一个宿主的连接所有者；消费者在自己的生命周期内借用客户端。

    component 只连接声明，config 选择连接，prepare 才创建网络资源。
    stop 封闭借用入口并取消、等待剩余借用；clean 在消费者清理后释放客户端。
    关闭等待取消或超时不再次打断正在执行的收尾，可再次等待；失败连接不自动重连。
    客户端及 SDK 类型仅供适配层使用，不应写入 ctx 或传出到 world/agent 契约。
    """

    def __init__(
        self,
        ctx: Context,
        hooks: HookConnections,
        *,
        instance_id: str = "aurora_adapter/mcp",
        resolve_env: Callable[[str], str | None] = os.environ.get,
        workspace_root: Path | None = None,
    ) -> None:
        if not instance_id or not instance_id.strip():
            raise ValueError("MCP 所有者身份不能为空")
        self._ctx, self._hooks, self._instance_id = ctx, hooks, instance_id
        self._resolve_env = resolve_env
        self._workspace_root = workspace_root
        self._connections: dict[str, _Connection] = {}
        self._connected = False
        self._configured = False
        self._prepared = False
        self._closing = False
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def instance_id(self) -> str:
        """供实际消费者声明生命周期依赖。"""
        return self._instance_id

    def server_configurations(self) -> dict[str, dict]:
        """返回 config 阶段选定声明的副本；消费者与连接使用同一配置快照。"""
        if not self._configured:
            raise RuntimeError("MCP 客户端尚未配置")
        return deepcopy({name: binding.config for name, binding in self._connections.items()})

    def _check_loop(self) -> None:
        if self._loop is not asyncio.get_running_loop():
            raise RuntimeError("MCP 客户端必须在准备它的事件循环使用")

    def _publish(self, binding: _Connection) -> None:
        self._ctx.set(
            CLIENT_STATUS,
            {
                "phase": binding.phase,
                "error": binding.error,
                "error_location": binding.error_location,
                "accepting": self._prepared and not self._closing and binding.phase == "ready",
                "type": binding.config["type"],
                "configured_protocol": binding.negotiation.configured_protocol,
                "negotiated_protocol": binding.negotiation.negotiated_protocol,
                "negotiation_attempts": binding.negotiation.attempts.copy(),
                "capabilities": binding.capabilities.copy(),
            },
            location={"owner": self._instance_id, "connection_id": binding.config["connection_id"]},
        )

    def component(self, *, depends_on: tuple[str, ...] = ()) -> LifecycleComponent:
        """依赖配置服务；消费者须将此组件列为依赖，保证准备和关闭顺序。"""
        if self._connected or self._configured or self._closing:
            raise RuntimeError("MCP 生命周期已连接或不再允许装配")
        links = []
        try:
            for phase, method in (
                (CONFIG, self.configure),
                (PREPARE, self.prepare),
                (STOP, self.stop),
                (CLEAN, self.clean),
            ):
                entry = entry_from(method, provider="aurora_adapter.mcp")
                links.append(
                    self._hooks.connect(
                        phase,
                        entry.id,
                        slot_instance=self._instance_id,
                        handler_instance=self._instance_id,
                        target=method,
                    )
                )
        except Exception:
            for link in links:
                self._hooks.disconnect(link)
            raise
        self._connected = True
        return LifecycleComponent(
            self._instance_id,
            depends_on=tuple(dict.fromkeys(("aurora_config", *depends_on))),
            stop_accepting=self.stop_accepting,
        )

    @hook_handler("org.aurora.adapter:handlers/mcp/configure", slot=CONFIG)
    def configure(self) -> None:
        if self._configured or self._closing:
            raise RuntimeError("MCP 配置只允许装配一次")
        values = cast(dict, MCP_CONFIG.parse(self._ctx.get(CONFIG_STATE)))
        self._connections = {
            name: _Connection(item, Negotiation(item["protocol"])) for name, item in configured_servers(values).items()
        }
        self._configured = True
        for binding in self._connections.values():
            binding.idle.set()
            self._publish(binding)

    async def _serve(self, binding: _Connection) -> None:
        try:
            async with AsyncExitStack() as stack:
                async with asyncio.timeout(binding.config["timeout"]["startup"]):
                    client = await stack.enter_async_context(
                        transports.open_client(
                            binding.config, self._resolve_env, binding.negotiation, workspace_root=self._workspace_root
                        )
                    )
                binding.client = client
                binding.negotiation.negotiated_protocol = client.protocol_version
                binding.capabilities = [
                    name for name in CAPABILITIES if getattr(client.server_capabilities, name) is not None
                ]
                binding.phase = "ready"
                self._publish(binding)
                binding.ready.set()
                await binding.close.wait()
                binding.phase = "closing"
                self._publish(binding)
            binding.phase = "closed"
        except asyncio.CancelledError:
            code = "close_failed" if binding.phase == "closing" else "connect_cancelled"
            binding.phase, binding.error = "failed", code
        except Exception as error:  # noqa: BLE001 — SDK 后台异常统一转为固定诊断，不泄露远端原文。
            if isinstance(error, MCPClientError):
                binding.error_location = error.location
            code = error_code(error, "close_failed" if binding.phase == "closing" else "connect_failed")
            if binding.phase == "closing" and not (code == "transport_failed" and binding.error == "request_failed"):
                code = "close_failed"
            binding.phase, binding.error = "failed", code
        finally:
            binding.client = None
            self._publish(binding)
            binding.ready.set()

    @hook_handler("org.aurora.adapter:handlers/mcp/prepare", slot=PREPARE)
    async def prepare(self) -> None:
        if not self._configured or self._loop is not None or self._closing:
            raise RuntimeError("MCP 客户端尚未配置或已开始准备")
        self._loop = asyncio.get_running_loop()
        for identity, binding in self._connections.items():
            binding.phase = "connecting"
            self._publish(binding)
            binding.task = asyncio.create_task(self._serve(binding), name=f"aurora-mcp:{identity}")
            await binding.ready.wait()
            if binding.phase != "ready":
                raise MCPClientError(
                    binding.error or "connect_failed", location=binding.error_location or f"servers.{identity}"
                )
        self._prepared = True
        for binding in self._connections.values():
            self._publish(binding)

    @asynccontextmanager
    async def connection(self, connection_id: str) -> AsyncIterator[Client]:
        """借用期间保持资源存活；调用方不得保存客户端供借用结束后使用。"""
        self._check_loop()
        binding = self._connections.get(connection_id)
        if binding is None:
            raise MCPClientError("connection_unavailable")
        if not self._prepared or self._closing or binding.phase != "ready" or binding.client is None:
            raise MCPClientError("not_accepting")
        task = asyncio.current_task()
        assert task is not None
        binding.users[task] = binding.users.get(task, 0) + 1
        binding.idle.clear()
        try:
            yield binding.client
        except Exception:  # noqa: BLE001 — 适配层借用边界不向宿主泄露远端异常文本。
            binding.error = "request_failed"
            self._publish(binding)
            raise MCPClientError("request_failed") from None
        finally:
            binding.users[task] -= 1
            if not binding.users[task]:
                del binding.users[task]
                binding.cancelled_users.discard(task)
            if not binding.users:
                binding.idle.set()

    def stop_accepting(self) -> None:
        """永久封闭新借用，不提前关闭现有消费者所需连接。"""
        self._closing = True
        for binding in self._connections.values():
            self._publish(binding)

    @hook_handler("org.aurora.adapter:handlers/mcp/stop", slot=STOP)
    async def stop(self) -> None:
        self.stop_accepting()
        for binding in self._connections.values():
            async with asyncio.timeout(binding.config["timeout"]["shutdown"]):
                await self._drain(binding)

    async def _drain(self, binding: _Connection) -> None:
        for task in tuple(binding.users):
            if task is asyncio.current_task():
                raise RuntimeError("不能在借用客户端的任务内等待所有者关闭")
            if task not in binding.cancelled_users:
                task.cancel()
                binding.cancelled_users.add(task)
        await binding.idle.wait()
        if binding.task is not None and binding.phase == "connecting" and not binding.cancel_requested:
            binding.cancel_requested = True
            binding.task.cancel()

    @hook_handler("org.aurora.adapter:handlers/mcp/clean", slot=CLEAN)
    async def clean(self) -> None:
        self.stop_accepting()
        for binding in reversed(tuple(self._connections.values())):
            async with asyncio.timeout(binding.config["timeout"]["shutdown"]):
                await self._drain(binding)
                binding.close.set()
                if binding.task is not None and not binding.task.cancelled():
                    await asyncio.shield(binding.task)
            if binding.task is not None and binding.task.cancelled():
                binding.phase, binding.error = "failed", "connect_cancelled"
                self._publish(binding)
            if binding.error == "close_failed":
                raise MCPClientError("close_failed")
