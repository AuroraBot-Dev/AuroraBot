from __future__ import annotations

from typing import TYPE_CHECKING

from src.memory.service import MemoryService

if TYPE_CHECKING:
    from pathlib import Path


def test_memory_service_needs_no_model_or_embedding_credentials(tmp_path: Path) -> None:
    MemoryService(tmp_path)
    assert (tmp_path / "memory.sqlite3").is_file()
