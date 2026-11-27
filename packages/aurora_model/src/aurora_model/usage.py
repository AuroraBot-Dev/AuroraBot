"""仅记录供应商报告的用量与调用关联；不包含请求、响应正文或凭证。"""

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic

logger = logging.getLogger(__name__)
_scope: ContextVar[dict[str, str] | None] = ContextVar("model_usage_scope", default=None)


@contextmanager
def usage_scope(purpose: str, **identity: str):
    """为当前异步调用标注用途及 run_id、execution_id 或 decision_id。"""
    if set(identity) - {"run_id", "execution_id", "decision_id"}:
        raise ValueError("未知的模型调用关联字段")
    token = _scope.set({"purpose": purpose, **identity})
    try:
        yield
    finally:
        _scope.reset(token)


class UsageRecord:
    """每次请求仅输出一条日志；流中重复用量按累计快照更新，不相加。"""

    def __init__(self, kind: str, model: str) -> None:
        self.labels = {"purpose": kind, **(_scope.get() or {}), "model": model}
        self.started = monotonic()
        self.tokens: dict[str, int] = {}
        self.complete = False
        self._line = b""
        self._data = b""
        self._oversized = False

    def read(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        message = payload.get("message")
        if isinstance(message, dict):
            self.read(message)
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return
        fields = {
            "input_tokens": ("input_tokens", "prompt_tokens"),
            "output_tokens": ("output_tokens", "completion_tokens"),
            "total_tokens": ("total_tokens",),
            "cached_input_tokens": ("cached_tokens", "cache_read_input_tokens", "prompt_cache_hit_tokens"),
            "cache_write_tokens": ("cache_write_tokens", "cache_creation_input_tokens"),
            "reasoning_tokens": ("reasoning_tokens",),
        }
        for target, names in fields.items():
            for name in names:
                value = usage.get(name)
                if type(value) is int and value >= 0:
                    self.tokens[target] = value
                    break
        for key, name, target in (
            ("prompt_tokens_details", "cached_tokens", "cached_input_tokens"),
            ("input_tokens_details", "cached_tokens", "cached_input_tokens"),
            ("completion_tokens_details", "reasoning_tokens", "reasoning_tokens"),
            ("output_tokens_details", "reasoning_tokens", "reasoning_tokens"),
        ):
            details = usage.get(key)
            value = details.get(name) if isinstance(details, dict) else None
            if type(value) is int and value >= 0:
                self.tokens[target] = value

    def feed(self, chunk: bytes) -> None:
        """读取原始 SSE 的 usage，最多缓冲 1 MiB 单事件；超限仅放弃该事件的计量。"""
        self._line += chunk
        while b"\n" in self._line:
            line, self._line = self._line.split(b"\n", 1)
            line = line.rstrip(b"\r")
            if not line:
                if not self._oversized:
                    try:
                        self.read(json.loads(self._data))
                    except (ValueError, UnicodeError):
                        pass
                self._data, self._oversized = b"", False
            elif line.startswith(b"data:") and not self._oversized:
                self._data += line[5:].lstrip(b" ") + b"\n"
            if len(self._data) > 1024 * 1024:
                self._data, self._oversized = b"", True
        if len(self._line) > 1024 * 1024:
            self._line, self._oversized = b"", True

    def finish(self, status: str) -> None:
        logger.info(
            "模型用量 %s",
            json.dumps(
                {
                    **self.labels,
                    "status": status,
                    "usage_reported": bool(self.tokens),
                    "tokens": self.tokens,
                    "elapsed_seconds": round(monotonic() - self.started, 3),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
