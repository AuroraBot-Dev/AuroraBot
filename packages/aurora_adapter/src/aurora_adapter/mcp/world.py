"""显式选择的 MCP 资源通知转为 world 输入；不引入 agent 或第二个调度器。"""

import asyncio
import logging
import time
from typing import cast
from uuid import uuid4

from aurora_core import Id
from aurora_core.ctx import Context, StateKey
from aurora_core.discovery import Plugin
from aurora_core.hooks import HookConnections
from aurora_core.json_data import decode_json, encode_json
from aurora_core.lifecycle import LifecycleComponent
from aurora_core.registry import RegistryEntry
from aurora_world import (
    SOURCES,
    MessageConflictError,
    SourceEmit,
    SourceInstance,
    SourceSpec,
    SourceUnavailableError,
    WorldRecords,
)
from aurora_world.configuration import configured_sources_component
from mcp import Client
from mcp.client.subscriptions import ResourceUpdated, Subscription, SubscriptionLost, ToolsListChanged
from mcp.types import TextResourceContents

from .clients import MCPClients
from .configuration import PROTOCOL_VERSION
from .world_config import WORLD_CONFIG

WORLD_SOURCE = Id("org.aurora.adapter:sources/mcp/resources")
WORLD_STATUS = Id("org.aurora.adapter:state/mcp/world")
logger = logging.getLogger(__name__)


class MCPWorldError(RuntimeError):
    """来源专用固定诊断，不包含远端异常或资源内容。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"MCP 世界来源失败：{code}")


class _ResourceSource:
    def __init__(self, ctx: Context, clients: MCPClients, source_id: str, emit: SourceEmit, config: dict) -> None:
        self.ctx, self.clients, self.source_id, self.emit, self.config = ctx, clients, source_id, emit, config
        self.resources = {item["uri"]: item["mode"] for item in config["resources"]}
        self.queue: asyncio.Queue[str] = asyncio.Queue(config["buffer_size"])
        self.ready = asyncio.Event()
        self.task: asyncio.Task[None] | None = None
        self.stopping = False
        self.cancel_requested = False
        self.phase = "prepared"
        self.error: str | None = None
        self.tools_dirty = False
        self.inflight = 0
        self.discarded = 0
        self.accepted = 0
        self.duplicates = 0
        self.close_failed = False
        self._publish()

    def _publish(self) -> None:
        self.ctx.set(
            WORLD_STATUS,
            {
                "phase": self.phase,
                "error": self.error,
                "tools_dirty": self.tools_dirty,
                "accepted": self.accepted,
                "duplicates": self.duplicates,
                "discarded": self.discarded,
                "close_error": "subscription_close_failed" if self.close_failed else None,
                "identity_modes": sorted(
                    {"source_message" if mode == "event" else "local_observation" for mode in self.resources.values()}
                ),
            },
            location={"source_id": self.source_id},
        )

    def _fail(self, code: str) -> None:
        if self.error is None:
            self.error = code
            self.phase = "failed"
            self._publish()
            logger.error("MCP 世界来源失败：source_id=%s code=%s", self.source_id, code)

    async def _receive(self, subscription: Subscription) -> None:
        try:
            async for event in subscription:
                if isinstance(event, ToolsListChanged):
                    self.tools_dirty = True
                    self._publish()
                elif isinstance(event, ResourceUpdated):
                    if event.uri not in self.resources:
                        raise MCPWorldError("unselected_resource")
                    try:
                        self.queue.put_nowait(event.uri)
                    except asyncio.QueueFull:
                        self.discarded += 1
                        raise MCPWorldError("buffer_overflow") from None
            raise MCPWorldError("subscription_ended")
        except SubscriptionLost:
            self._fail("subscription_lost")
            raise MCPWorldError("subscription_lost") from None
        except MCPWorldError as error:
            self._fail(error.code)
            raise

    async def _message(self, client: Client, uri: str) -> tuple[str, dict]:
        mode = self.resources[uri]
        payload: dict = {"kind": "mcp.resource.updated", "connection_id": self.config["connection_id"], "uri": uri}
        contents = []
        if mode != "notification":
            try:
                result = await client.read_resource(uri)
            except Exception:  # noqa: BLE001 — 资源读取只公开固定错误码。
                raise MCPWorldError("resource_read_failed") from None
            contents = result.contents
            values = [item.model_dump(mode="json", by_alias=True, exclude_none=True) for item in contents]
            if len(encode_json(values).encode("utf-8")) > self.config["max_content_bytes"]:
                raise MCPWorldError("resource_too_large")
            payload["contents"] = values
        if mode == "event":
            if len(contents) != 1 or not isinstance(contents[0], TextResourceContents):
                raise MCPWorldError("invalid_event")
            try:
                event = decode_json(contents[0].text)
            except (ValueError, TypeError):
                raise MCPWorldError("invalid_event") from None
            if (
                not isinstance(event, dict)
                or type(event.get("message_id")) is not str
                or not event["message_id"].strip()
            ):
                raise MCPWorldError("event_identity_missing")
            if set(event) != {"message_id", "payload"}:
                raise MCPWorldError("invalid_event")
            payload.pop("contents")
            payload.update(
                kind="mcp.event", identity="source_message", message_id=event["message_id"], payload=event["payload"]
            )
            return encode_json(["event", self.config["connection_id"], uri, event["message_id"]]), payload
        payload.update(identity="local_observation", observed_at=time.time())
        return f"observation:{uuid4().hex}", payload

    async def _consume(self, client: Client) -> None:
        try:
            while True:
                uri = await self.queue.get()
                self.inflight = 1
                message_id, payload = await self._message(client, uri)
                if self.error or self.stopping:
                    return
                try:
                    receipt = self.emit(message_id=message_id, payload=payload)
                except MessageConflictError:
                    raise MCPWorldError("event_conflict") from None
                except SourceUnavailableError:
                    raise
                except Exception:  # noqa: BLE001 — 不将接收方异常文本写入来源状态。
                    raise MCPWorldError("world_rejected") from None
                self.inflight = 0
                self.duplicates += int(receipt.duplicate)
                self.accepted += int(not receipt.duplicate)
                self._publish()
        except MCPWorldError as error:
            self._fail(error.code)
            raise

    async def _watch(self) -> None:
        exiting_subscription = False
        try:
            async with self.clients.connection(self.config["connection_id"]) as client:
                try:
                    if client.protocol_version != PROTOCOL_VERSION:
                        raise MCPWorldError("unsupported_subscription_protocol")
                    if (
                        any(mode != "notification" for mode in self.resources.values())
                        and client.server_capabilities.resources is None
                    ):
                        raise MCPWorldError("missing_resource_capability")
                    if self.config["watch_tools"] and client.server_capabilities.tools is None:
                        raise MCPWorldError("missing_tools_capability")
                    async with client.listen(
                        resource_subscriptions=list(self.resources),
                        tools_list_changed=self.config["watch_tools"],
                    ) as subscription:
                        try:
                            honored = subscription.honored
                            if set(honored.resource_subscriptions or ()) != set(self.resources) or (
                                self.config["watch_tools"] and not honored.tools_list_changed
                            ):
                                raise MCPWorldError("subscription_not_honored")
                            self.phase = "listening"
                            self._publish()
                            self.ready.set()
                            try:
                                async with asyncio.TaskGroup() as group:
                                    group.create_task(self._receive(subscription))
                                    group.create_task(self._consume(client))
                            except* MCPWorldError:
                                pass
                            except* SourceUnavailableError:
                                self._fail("world_not_accepting")
                            except* Exception:  # noqa: BLE001 — 消费任务失败统一脱敏，订阅仍须退出。
                                self._fail("subscription_failed")
                        finally:
                            exiting_subscription = True
                except MCPWorldError as error:
                    self._fail(error.code)
                    raise
                except Exception:
                    if exiting_subscription:
                        self.close_failed = True
                        self._fail("subscription_close_failed")
                    else:
                        self._fail("subscription_failed")
                    raise
        except asyncio.CancelledError:
            if not self.stopping:
                self._fail("subscription_cancelled")
        except Exception:  # noqa: BLE001 — 借用失败也不能留下未观察的后台异常。
            if not self.stopping:
                self._fail("connection_unavailable")
        finally:
            self.discarded += self.queue.qsize() + self.inflight
            while not self.queue.empty():
                self.queue.get_nowait()
            self.inflight = 0
            if self.discarded:
                logger.warning("MCP 世界来源结束时有未接纳通知：source_id=%s count=%s", self.source_id, self.discarded)
            if self.discarded and self.error is None:
                self._fail("stopped_with_pending")
            if self.error is None:
                self.phase = "stopped"
            self._publish()
            self.ready.set()

    async def start(self) -> None:
        if self.task is not None or self.stopping:
            raise RuntimeError("MCP 世界来源只允许启动一次")
        self.phase = "starting"
        self._publish()
        self.task = asyncio.create_task(self._watch(), name=f"mcp-world:{self.source_id}")
        await self.ready.wait()
        if self.error:
            raise MCPWorldError(self.error)

    async def run(self) -> None:
        assert self.task is not None
        await asyncio.shield(self.task)
        if self.error and not self.stopping:
            raise MCPWorldError(self.error)

    async def stop(self) -> None:
        self.stopping = True
        if self.task is not None:
            if not self.task.done() and not self.cancel_requested:
                self.cancel_requested = True
                self.task.cancel()
            await asyncio.wait({self.task})
            if self.close_failed:
                raise MCPWorldError("subscription_close_failed")

    async def close(self) -> None:
        await self.stop()


class _WorldFactory:
    def __init__(self, ctx: Context, clients: MCPClients) -> None:
        self.ctx, self.clients = ctx, clients

    async def __call__(self, *, source_id: str, emit: SourceEmit, config: dict[str, object]) -> SourceInstance:
        values = cast(dict, WORLD_CONFIG.parse(config))
        source = _ResourceSource(self.ctx, self.clients, source_id, emit, values)
        return SourceInstance(source.start, source.stop, source.close, source.run)


async def _unbound_factory(*, source_id: str, emit: SourceEmit, config: dict[str, object]) -> SourceInstance:
    raise RuntimeError("MCP 世界来源尚未装配客户端所有者")


def mcp_world_component(
    ctx: Context,
    hooks: HookConnections,
    clients: MCPClients,
    records: WorldRecords,
    *,
    instance_id: str = "aurora_world/sources",
    depends_on: tuple[str, ...] = (),
) -> LifecycleComponent:
    """装配同一 world 来源所有者并注入共享客户端，替代 configured_sources_component。"""
    spec = ctx.registry.get(WORLD_SOURCE).target
    if not isinstance(spec, SourceSpec) or spec.factory is not _unbound_factory:
        raise TypeError("MCP 世界来源定义不匹配")
    return configured_sources_component(
        ctx,
        hooks,
        records,
        instance_id=instance_id,
        depends_on=tuple(dict.fromkeys((clients.instance_id, *depends_on))),
        source_factories={WORLD_SOURCE: _WorldFactory(ctx, clients)},
    )


def _validate_status(value: object) -> None:
    encode_json(value)


def plugin() -> Plugin:
    """只声明来源和非持久诊断，发现不连接客户端或订阅服务。"""
    return Plugin(
        "aurora_adapter.mcp.world",
        (
            RegistryEntry(
                WORLD_SOURCE, "source", SourceSpec(_unbound_factory), "aurora_adapter.mcp.world", register_to=SOURCES
            ),
            RegistryEntry(
                WORLD_STATUS, "state_key", StateKey(_validate_status, persistent=False), "aurora_adapter.mcp.world"
            ),
        ),
        requires=("aurora_adapter.mcp", "aurora_world.configuration"),
    )
