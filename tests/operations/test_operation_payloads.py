"""大对象编码不阻塞事件循环，恢复仍遵守原始内容和格式约束。"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

import pytest

from aurora_bot.artifacts.store import FileArtifactStore
from aurora_bot.contracts.artifact import ArtifactInfo, ArtifactIntegrityError
from aurora_bot.contracts.artifact_codec import read_artifact
from aurora_bot.contracts.data import freeze_object
from aurora_bot.contracts.resource import ResourceKey
from aurora_bot.operations import payloads
from aurora_bot.operations.payloads import OperationPayloads

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_KEY = ResourceKey.parse("lab:operations/request/large")


@pytest.mark.parametrize("large", [False, True])
def test_all_json_encoding_runs_off_the_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, large: bool
) -> None:
    """包括跨过内联上限的单个字符串在内，真实编码都在线程中完成。"""
    actual_encoder = payloads.json_bytes
    threads: list[int] = []
    loop_thread = threading.get_ident()

    def encode(value: object) -> Iterator[bytes]:
        """观察真实编码所在的线程，不替换编码算法或实际存储。"""
        threads.append(threading.get_ident())
        yield from actual_encoder(value)

    monkeypatch.setattr(payloads, "json_bytes", encode)

    async def scenario() -> None:
        codec = OperationPayloads(FileArtifactStore(tmp_path), 4096)
        original = freeze_object({"data": "中文" * (4096 if large else 1), "items": [[True, None, 3.5]]})
        saved = await codec.save(_KEY, original, media_type="application/json")
        if large:
            assert isinstance(saved, ArtifactInfo)
            assert await codec.load(saved, media_type="application/json") == original
            with pytest.raises(ArtifactIntegrityError, match="媒体类型"):
                await codec.load(saved, media_type="text/plain")
        else:
            assert not isinstance(saved, ArtifactInfo)
            assert saved == original
        assert threads
        assert loop_thread not in threads

    asyncio.run(scenario())


@pytest.mark.parametrize("field,value", [("key", None), ("revision", []), ("media_type", 1)])
def test_malformed_resource_descriptions_fail_at_the_protocol_boundary(field: str, value: object) -> None:
    """损坏的线格式不能绕过值对象后变成难以定位的属性异常。"""
    data = {"key": str(_KEY), "revision": "a" * 64, "size": 3, "media_type": "application/json"}
    with pytest.raises(ValueError, match="内容资源描述"):
        read_artifact({**data, field: value})
