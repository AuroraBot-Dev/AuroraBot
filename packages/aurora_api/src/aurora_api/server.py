"""同一宿主事件循环中的本机 HTTP/WS ctx 传输。"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager, suppress
from functools import partial
from typing import cast

from aiohttp import WSMsgType, web
from aurora_core.ctx import StateAddress, StateChange, StateKey
from aurora_core.ids import Id
from aurora_core.invocation import invoke_operation
from aurora_core.json_data import decode_json, encode_json
from aurora_core.registry import DefinitionRegistry

from .access import AccessPolicy
from .endpoints import ENDPOINTS, Endpoint, EndpointReceiver
from .protocol import CHANGED, HTTP_ACTIONS, SUBSCRIBE, UNSUBSCRIBE, WATCH_PATH, address_data, change_data, error_data

logger = logging.getLogger(__name__)


def _error(error: Exception) -> tuple[int, dict[str, object]]:
    # 错误载荷使用固定消息，不向客户端回传状态值或校验器内部信息。
    if isinstance(error, PermissionError):
        return 403, error_data("forbidden", "状态未开放")
    if isinstance(error, KeyError):
        return 404, error_data("not_found", "状态不存在")
    if isinstance(error, (ValueError, TypeError)):
        return 400, error_data("invalid_request", "请求格式或状态值无效")
    logger.error("ctx API 请求失败", exc_info=error)
    return 500, error_data("internal_error", "宿主处理失败")


def _filters(data: object, allowed: frozenset[Id], *, action: str) -> dict[str, object]:
    fields = {"key", "location", "value"} if action == "set" else {"key", "location"}
    if not isinstance(data, dict) or set(data) - fields:
        raise ValueError("请求须为仅包含约定字段的 JSON 对象")
    values: dict[str, object] = {}
    if "key" in data:
        if not isinstance(data["key"], str):
            raise TypeError("key 须为字符串")
        key = Id(data["key"])
        if key not in allowed:
            raise PermissionError("状态未开放")
        values["key"] = key
    elif action not in ("list", "watch"):
        raise ValueError("缺少 key")
    if "location" in data:
        location = data["location"]
        if not isinstance(location, dict) or any(
            not isinstance(key, str) or not key or not isinstance(value, str) or not value
            for key, value in location.items()
        ):
            raise ValueError("location 须包含非空字符串键值对")
        values["location"] = location
    if action == "set":
        if "value" not in data:
            raise ValueError("缺少 value")
        values["value"] = data["value"]
    return values


def create_application(
    registry: DefinitionRegistry,
    *,
    keys: Iterable[Id],
    read_only_keys: Iterable[Id] = (),
    queue_limit: int = 256,
    endpoints: Iterable[Id] = (),
    access: AccessPolicy | None = None,
) -> web.Application:
    """仅开放显式选择的完整状态键；同一键的全部 location 均开放。"""
    writable, readonly = frozenset(keys), frozenset(read_only_keys)
    if writable & readonly:
        raise ValueError("状态键不能同时声明为只读和可写")
    allowed = writable | readonly
    for key in allowed:
        entry = registry.get(key)
        if entry.kind != "state_key" or not isinstance(entry.target, StateKey):
            raise ValueError("开放目标须为已登记的状态键")
    if queue_limit <= 0:
        raise ValueError("订阅队列上限必须为正数")
    sockets: set[web.WebSocketResponse] = set()
    policy = access or AccessPolicy()
    methods: dict[str, set[str]] = {}

    @web.middleware
    async def local_access(
        request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]
    ) -> web.StreamResponse:
        origins = request.headers.getall("Origin", [])
        if (
            len(request.headers.getall("Host", [])) != 1
            or request.url.host not in policy.allowed_hosts
            or len(origins) > 1
            or (origins and origins[0] not in policy.allowed_origins)
        ):
            return web.json_response(error_data("forbidden", "请求来源或主机未开放"), status=403)

        def cors(response: web.StreamResponse) -> web.StreamResponse:
            if not response.prepared:
                if policy.token is not None:
                    response.headers["Cache-Control"] = "no-store"
                if origins:
                    response.headers["Access-Control-Allow-Origin"] = origins[0]
                    response.headers.add("Vary", "Origin")
            return response

        if request.method == "OPTIONS":
            method = request.headers.get("Access-Control-Request-Method", "")
            headers = {
                value.strip().lower()
                for value in request.headers.get("Access-Control-Request-Headers", "").split(",")
                if value.strip()
            }
            if (
                not origins
                or method not in methods.get(request.path, set())
                or headers - {"authorization", "content-type"}
            ):
                return cors(web.json_response(error_data("forbidden", "预检请求未开放"), status=403))
            return cors(
                web.Response(
                    status=204,
                    headers={
                        "Access-Control-Allow-Methods": method,
                        "Access-Control-Allow-Headers": "Authorization, Content-Type",
                    },
                )
            )
        if policy.token is not None and not (request.method == "GET" and request.path == WATCH_PATH):
            authorization = request.headers.getall("Authorization", [])
            if (
                len(authorization) != 1
                or not authorization[0].lower().startswith("bearer ")
                or not policy.accepts_token(authorization[0][7:])
            ):
                return cors(
                    web.json_response(
                        error_data("unauthorized", "访问令牌无效或缺失"),
                        status=401,
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                )
        try:
            return cors(await handler(request))
        except web.HTTPException as error:
            if error.status == 404:
                return cors(web.json_response(error_data("not_found", "接口未开放"), status=404))
            return cors(error)
        except Exception as error:  # noqa: BLE001 — 在传输边界统一映射错误。
            status, body = _error(error)
            return cors(web.json_response(body, status=status))

    async def handle(action: str, request: web.Request) -> web.Response:
        if request.content_type != "application/json":
            return web.json_response(error_data("invalid_request", "请求需要 application/json"), status=415)
        values = _filters(decode_json(await request.text()), allowed, action=action)
        if action in ("set", "delete") and values["key"] not in writable:
            raise PermissionError("状态只允许读取和订阅")
        result = await invoke_operation(registry, HTTP_ACTIONS[action][1], **values)
        if action == "list":
            addresses = cast(tuple[StateAddress, ...], result)
            result = [address_data(address) for address in addresses if address.key in allowed]
        return web.Response(text=encode_json({"result": result}), content_type="application/json")

    async def product(endpoint: Endpoint, action: str, request: web.Request) -> web.Response:
        if request.content_type != "application/json":
            return web.json_response(error_data("invalid_request", "请求需要 application/json"), status=415)
        limit = endpoint.http[action].get("max_body_bytes", request.client_max_size)
        request = request.clone(client_max_size=limit)
        status, body = await endpoint.handle(action, decode_json(await request.text()))
        return web.Response(text=encode_json(body), content_type="application/json", status=status)

    async def watch(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30, timeout=2, max_msg_size=1024 * 1024)
        await ws.prepare(request)
        sockets.add(ws)
        handle: str | None = None
        tasks: list[asyncio.Task] = []
        queue: asyncio.Queue[tuple[str, int | None]] = asyncio.Queue(maxsize=queue_limit)
        failed = False

        def notify(change: StateChange) -> None:
            nonlocal failed
            if failed or change.address.key not in allowed:
                return
            try:
                message = encode_json({"type": "event", "event": CHANGED, "data": change_data(change)})
                queue.put_nowait((message, None))
            except (asyncio.QueueFull, TypeError, ValueError) as error:
                failed = True
                while not queue.empty():
                    queue.get_nowait()
                code = "slow_consumer" if isinstance(error, asyncio.QueueFull) else "non_json_state"
                message = encode_json({"type": "error", **error_data(code, "订阅中断，请重新连接并读取状态")})
                queue.put_nowait((message, 1013))

        async def send() -> None:
            while True:
                message, close_code = await queue.get()
                async with asyncio.timeout(5):
                    await ws.send_str(message)
                if close_code is not None:
                    await ws.close(code=close_code)
                    return

        async def receive() -> None:
            async for message in ws:
                if message.type in (WSMsgType.TEXT, WSMsgType.BINARY):
                    await ws.close(code=1008, message=b"Close the connection to unsubscribe")
                    return

        try:
            async with asyncio.timeout(10):
                data = await ws.receive_json(loads=decode_json)
            if policy.token is not None and (
                not isinstance(data, dict) or not policy.accepts_token(data.pop("access_token", None))
            ):
                await ws.send_json({"type": "error", **error_data("unauthorized", "访问令牌无效或缺失")})
                await ws.close(code=1008)
                return ws
            values = _filters(data, allowed, action="watch")
            handle = cast(str, await invoke_operation(registry, SUBSCRIBE, notify, **values))
            await ws.send_json({"type": "ready"})
            tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (ConnectionError, TimeoutError):
            await ws.close(code=1013, message=b"Reconnect and refresh state")
        except Exception as error:  # noqa: BLE001 — 握手后通过 WS 信封报告错误。
            if not ws.closed:
                _, body = _error(error)
                with suppress(ConnectionError, TimeoutError):
                    async with asyncio.timeout(2):
                        await ws.send_json({"type": "error", **body})
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if handle is not None:
                await invoke_operation(registry, UNSUBSCRIBE, handle)
            sockets.discard(ws)
            await ws.close()
        return ws

    async def shutdown(app: web.Application) -> None:
        await asyncio.gather(*(ws.close(code=1001, message=b"Host stopping") for ws in tuple(sockets)))

    app = web.Application(middlewares=[local_access], client_max_size=1024 * 1024)
    for action, (path, _) in HTTP_ACTIONS.items():
        app.router.add_post(path, partial(handle, action))
        methods.setdefault(path, set()).add("POST")
    app.router.add_get(WATCH_PATH, watch)
    for identity in endpoints:
        entry = registry.get(identity)
        if entry.register_to != ENDPOINTS or EndpointReceiver().rejection_reason(entry) is not None:
            raise ValueError("开放目标须为有效的产品端点")
        endpoint = cast(Endpoint, entry.target)
        for action, binding in endpoint.http.items():
            app.router.add_route(binding["method"], binding["path"], partial(product, endpoint, action))
            methods.setdefault(binding["path"], set()).add(binding["method"])
    app.on_shutdown.append(shutdown)
    return app


@asynccontextmanager
async def serve(
    registry: DefinitionRegistry,
    *,
    keys: Iterable[Id],
    read_only_keys: Iterable[Id] = (),
    port: int = 10270,
    queue_limit: int = 256,
    endpoints: Iterable[Id] = (),
    access: AccessPolicy | None = None,
) -> AsyncGenerator[str, None]:
    """在宿主循环监听 IPv4 回环地址，退出时先关闭连接与订阅。"""
    if not 0 <= port <= 65535:
        raise ValueError("端口须在 0 至 65535 之间")
    app = create_application(
        registry, keys=keys, read_only_keys=read_only_keys, queue_limit=queue_limit, endpoints=endpoints, access=access
    )
    runner = web.AppRunner(app, access_log=None, shutdown_timeout=5)
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", port).start()
        yield f"http://127.0.0.1:{runner.addresses[0][1]}"
    finally:
        await runner.cleanup()
