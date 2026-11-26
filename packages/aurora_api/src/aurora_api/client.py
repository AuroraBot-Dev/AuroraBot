"""Python 客户端的 ctx 请求与显式订阅生命周期。"""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Self
from urllib.parse import urlsplit

from aiohttp import ClientSession, ClientTimeout, ClientWSTimeout, WSMsgType
from aurora_core.json_data import decode_json, encode_json

from .access import validate_token
from .protocol import CHANGED, HTTP_ACTIONS, WATCH_PATH


class RemoteError(RuntimeError):
    """服务端提供的稳定错误码与公开消息。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def _check_error(body: object) -> dict:
    if not isinstance(body, dict):
        raise TypeError("API 返回了无效信封")
    if "error" in body:
        error = body["error"]
        if not isinstance(error, dict) or not all(isinstance(error.get(key), str) for key in ("code", "message")):
            raise ValueError("API 返回了无效错误信封")
        raise RemoteError(error["code"], error["message"])
    return body


class CtxClient:
    """通过 async with 持有连接；关闭 watch 即取消订阅，不自动重连或重放。"""

    def __init__(self, url: str, *, token: str | None = None) -> None:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("连接地址须为 http(s)://主机:端口")
        self.url = url.rstrip("/")
        validate_token(token)
        self._token = token
        self._session: ClientSession | None = None

    async def __aenter__(self) -> Self:
        if self._session is not None:
            raise RuntimeError("客户端已连接")
        headers = {"Authorization": f"Bearer {self._token}"} if self._token is not None else {}
        self._session = ClientSession(timeout=ClientTimeout(total=10), json_serialize=encode_json, headers=headers)
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None
    ) -> None:
        await self._connection().close()
        self._session = None

    def _connection(self) -> ClientSession:
        if self._session is None:
            raise RuntimeError("请通过 async with 连接客户端")
        return self._session

    async def request(self, action: str, **values: object) -> object:
        if action not in HTTP_ACTIONS:
            raise ValueError("不支持的 ctx 动作")
        async with self._connection().post(
            self.url + HTTP_ACTIONS[action][0], json=values, allow_redirects=False
        ) as response:
            body = _check_error(await response.json(loads=decode_json))
            if response.status != 200 or "result" not in body:
                raise ValueError(f"API 返回了无效响应：HTTP {response.status}")
            return body["result"]

    @asynccontextmanager
    async def watch(self, **filters: object) -> AsyncGenerator[AsyncIterator[dict], None]:
        """收到 ready 后交付事件迭代器；仅包含订阅后的变化，revision 属于宿主当前 ctx。"""
        # aiohttp 的 attrs 动态构造签名无法被 basedpyright 完整识别。
        timeout = ClientWSTimeout(ws_receive=None, ws_close=2)  # pyright: ignore[reportCallIssue]
        async with self._connection().ws_connect(self.url + WATCH_PATH, heartbeat=30, timeout=timeout) as ws:
            await ws.send_json({**filters, **({"access_token": self._token} if self._token is not None else {})})
            body = _check_error(await ws.receive_json(timeout=10, loads=decode_json))
            if body.get("type") != "ready":
                raise ValueError("API 未确认订阅")

            async def events() -> AsyncIterator[dict]:
                async for message in ws:
                    if message.type != WSMsgType.TEXT:
                        raise ConnectionError("订阅连接异常，请重新连接并读取状态")
                    body = _check_error(decode_json(message.data))
                    if (
                        body.get("type") != "event"
                        or body.get("event") != CHANGED
                        or not isinstance(body.get("data"), dict)
                    ):
                        raise ValueError("API 返回了无效事件信封")
                    yield body["data"]
                raise ConnectionError("订阅连接已关闭，请重新连接并读取状态")

            yield events()
