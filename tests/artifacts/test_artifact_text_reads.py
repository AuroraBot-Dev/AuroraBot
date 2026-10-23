"""文本分块按字节寻址，同时保持 UTF-8 字符连续。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from aurora_bot.artifacts.operations import ArtifactOperation
from aurora_bot.artifacts.store import FileArtifactStore
from aurora_bot.contracts.operation import OperationKind, OperationRequest, OperationStatus
from aurora_bot.contracts.resource import ResourceKey

if TYPE_CHECKING:
    from pathlib import Path

_KEY = ResourceKey.parse("lab:memory/dataset/text")


def test_utf8_pages_reassemble_exact_text_without_losing_split_characters(tmp_path: Path) -> None:
    """调用者只按 next_offset 前进即可跨中文和四字节字符继续读取。"""

    async def scenario() -> None:
        content = "甲a🙂乙" * 3
        store = FileArtifactStore(tmp_path)
        info = await store.put(_KEY, content.encode(), media_type="text/plain")
        reader = ArtifactOperation(store, "read")
        offset = 0
        parts = []
        while True:
            result = await reader.execute(
                OperationRequest(
                    "read",
                    "lab:bot/test",
                    "test",
                    reader.definition.ref,
                    OperationKind.QUERY,
                    {
                        "key": str(_KEY),
                        "revision": info.ref.revision,
                        "offset": offset,
                        "limit": 5,
                        "encoding": "utf-8",
                    },
                )
            )
            assert result.status is OperationStatus.SUCCEEDED
            text = result.data["text"]
            assert text
            assert result.data["next_offset"] == offset + len(text.encode())
            assert "content_base64" not in result.data
            offset = result.data["next_offset"]
            parts.append(text)
            if not result.data["has_more"]:
                break
        assert "".join(parts) == content
        assert offset == info.size

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "content,offset,limit",
    [("中文".encode(), 1, 4), ("中文".encode(), 0, 2), (b"\xe4\xb8", 0, 4), (b"\xff", 0, 4)],
)
def test_invalid_utf8_position_or_content_fails_without_silent_replacement(
    tmp_path: Path, content: bytes, offset: int, limit: int
) -> None:
    """非法字节不能变成替换字符，也不能导致调用者反复读取零进度页面。"""

    async def scenario() -> None:
        store = FileArtifactStore(tmp_path)
        info = await store.put(_KEY, content)
        reader = ArtifactOperation(store, "read")
        result = await reader.execute(
            OperationRequest(
                "read",
                "lab:bot/test",
                "test",
                reader.definition.ref,
                OperationKind.QUERY,
                {
                    "key": str(_KEY),
                    "revision": info.ref.revision,
                    "offset": offset,
                    "limit": limit,
                    "encoding": "utf-8",
                },
            )
        )
        assert result.status is OperationStatus.FAILED
        assert result.message is not None and "UTF-8" in result.message
        assert not result.data
        assert not result.evidence_refs

    asyncio.run(scenario())


def test_empty_text_at_eof_is_a_valid_final_page(tmp_path: Path) -> None:
    """空资源和读取完毕后的空文本都有明确的结束标志。"""

    async def scenario() -> None:
        store = FileArtifactStore(tmp_path)
        info = await store.put(_KEY, b"")
        reader = ArtifactOperation(store, "read")
        result = await reader.execute(
            OperationRequest(
                "empty",
                "lab:bot/test",
                "test",
                reader.definition.ref,
                OperationKind.QUERY,
                {"key": str(_KEY), "revision": info.ref.revision, "encoding": "utf-8"},
            )
        )
        assert result.status is OperationStatus.SUCCEEDED
        assert result.data["text"] == ""
        assert result.data["next_offset"] == 0
        assert not result.data["has_more"]

    asyncio.run(scenario())
