# ruff: noqa: PLR2004
from __future__ import annotations

from typing import TYPE_CHECKING

from src.config.loader import load_configuration
from src.contracts.memory import MemoryEntry
from src.memory.config import build_memory_config
from src.memory.service import MemoryService

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_memory_config_requires_both_credentials(project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configuration = load_configuration(project_root)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    assert build_memory_config(configuration, project_root / "memory") is None

    monkeypatch.setenv("DEEPSEEK_API_KEY", "llm-secret")
    assert build_memory_config(configuration, project_root / "memory") is None

    monkeypatch.setenv("SILICONFLOW_API_KEY", "embedding-secret")
    value = build_memory_config(configuration, project_root / "memory")
    assert value is not None
    assert value["llm"]["config"]["openai_base_url"] == "https://api.deepseek.com/v1"
    assert value["embedder"]["config"]["openai_base_url"] == "https://api.siliconflow.cn/v1"
    assert value["vector_store"]["config"]["collection_name"] == "aurora_memory"


def test_memory_service_search_add_and_remember(tmp_path: Path) -> None:
    class Client:
        def __init__(self) -> None:
            self.added: list[object] = []

        def search(self, query: str, *, filters: dict[str, str]) -> dict[str, object]:
            assert query == "hello" and filters == {"user_id": "aurora"}
            return {"results": [{"memory": "one"}, {"memory": "two"}, {"ignored": True}]}

        def add(self, messages: object, *, user_id: str) -> None:
            self.added.append((messages, user_id))

    service = MemoryService(memory_dir=tmp_path)
    client = Client()
    service._available = True
    service._client = client
    assert service.search("hello", limit=1) == ["one"]
    assert service.add("remember this")
    assert service.remember(MemoryEntry("one", "session", "hello", "hi", "2026-01-02"))
    assert len(client.added) == 2


def test_memory_client_errors_are_nonfatal() -> None:
    class Broken:
        def search(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("search failed")

        def add(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("add failed")

    service = MemoryService.disabled()
    service._available = True
    service._client = Broken()
    assert service.search("hello") == []
    assert not service.add("hello")
