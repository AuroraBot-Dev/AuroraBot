from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCUMENTATION_FILES = (
    PROJECT_ROOT / "AGENTS.md",
    PROJECT_ROOT / "LOGGING.md",
    PROJECT_ROOT / "README.md",
    PROJECT_ROOT / "README.en.md",
    PROJECT_ROOT / "README.ja.md",
    PROJECT_ROOT / "index.html",
    *(PROJECT_ROOT / "docs").rglob("*.md"),
    *(PROJECT_ROOT / "extensions").rglob("*.md"),
    *(PROJECT_ROOT / "src").rglob("README.md"),
)
OBSOLETE_NARRATIVE = (
    "AuroraBot vNext",
    "legacy/",
    "legacy\\",
    "rebuild phase",
    "former implementation",
    "frozen root",
    "正在重建",
    "重建阶段",
    "冻结旧",
    "再構築中",
    "実行可能な Bot エントリポイントがありません",
)


def test_archived_source_mirror_is_not_part_of_current_tree() -> None:
    assert not (PROJECT_ROOT / "legacy").exists()
    ignored = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "legacy/" not in ignored
    assert "legacy\\" not in ignored


@pytest.mark.parametrize("path", DOCUMENTATION_FILES, ids=lambda path: str(path.relative_to(PROJECT_ROOT)))
def test_current_documentation_has_no_obsolete_project_narrative(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    matches = [phrase for phrase in OBSOLETE_NARRATIVE if phrase.casefold() in text.casefold()]
    assert not matches, f"{path.relative_to(PROJECT_ROOT)} contains obsolete narrative: {matches}"
