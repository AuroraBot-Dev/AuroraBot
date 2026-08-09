from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING

from src.memory.long_term import LongTermMemory
from src.memory.service import MemoryService

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_memory_service_needs_no_model_or_embedding_credentials(tmp_path: Path) -> None:
    MemoryService(tmp_path)
    assert (tmp_path / "memory.sqlite3").is_file()


def test_long_term_memory_uses_injected_models_and_scoped_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    class FakeMemory:
        embedding_model: object = object()

        @classmethod
        def from_config(cls, config: dict[str, object]) -> "FakeMemory":
            captured["config"] = config
            return cls()

        def add(self, text: str, **kwargs: object) -> None:
            captured["add"] = (text, kwargs)

        def search(self, query: str, **kwargs: object) -> dict[str, object]:
            captured["search"] = (query, kwargs)
            return {"results": [{"memory": "semantic result"}]}

    monkeypatch.setitem(sys.modules, "mem0", SimpleNamespace(Memory=FakeMemory))
    embed_calls: list[list[str]] = []

    def embed(texts: list[str]) -> list[list[float]]:
        embed_calls.append(texts)
        return [[1.0, 2.0] for _ in texts]

    memory = LongTermMemory(tmp_path, embed_fn=embed, llm_model="provider/quality-model")
    config = captured["config"]
    assert isinstance(config, dict)
    assert config["llm"] == {"provider": "litellm", "config": {"model": "provider/quality-model"}}
    assert config["history_db_path"] == str(tmp_path / "mem0-history.sqlite3")

    instance = memory._memory
    assert instance is not None
    assert instance.embedding_model.embed("query") == [1.0, 2.0]
    assert embed_calls == [["query"]]
    assert memory.search("session", "meaning", 3) == ("semantic result",)
    assert captured["search"] == ("meaning", {"filters": {"user_id": "session"}, "top_k": 3})
