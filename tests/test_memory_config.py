from __future__ import annotations

import logging
import os
import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING

from src.memory.long_term import LongTermMemory, _Mem0NoiseFilter
from src.memory.service import MemoryService

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_mem0_telemetry_is_disabled_by_default() -> None:
    """mem0 遥测默认关闭，避免 PostHog 数据外发与多客户端告警。"""
    assert os.environ.get("MEM0_TELEMETRY", "").lower() == "false"


def test_mem0_chroma_hybrid_and_spacy_warnings_are_suppressed() -> None:
    """Chroma 混合检索与 spaCy 缺失的告知性告警被过滤；其他 mem0 告警仍透传。"""
    suppressors = [f for f in logging.getLogger("mem0.memory.main").filters if isinstance(f, _Mem0NoiseFilter)]
    suppressors += [f for f in logging.getLogger("mem0.utils.spacy_models").filters if isinstance(f, _Mem0NoiseFilter)]
    assert suppressors

    def make_record(message: str) -> logging.LogRecord:
        logger = logging.getLogger("mem0.memory.main")
        return logger.makeRecord(logger.name, logging.WARNING, __file__, 1, message, (), None)

    hybrid = make_record(
        "The 'chroma' vector store does not support keyword search. "
        "Hybrid (BM25) scoring will be disabled and search will use semantic similarity only."
    )
    spacy = make_record(
        "Failed to load spaCy full model: spaCy is not installed. Install it with: pip install mem0ai[nlp]"
    )
    assert all(not item.filter(hybrid) for item in suppressors)
    assert all(not item.filter(spacy) for item in suppressors)
    other = make_record("Failed to embed memory text")
    assert all(item.filter(other) for item in suppressors)


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
