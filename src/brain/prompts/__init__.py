from __future__ import annotations
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


class Prompt:
    __slots__ = ("_filepath",)

    def __init__(self, filepath: Path) -> None:
        self._filepath = filepath

    def get_content(self) -> str:
        return self._filepath.read_text(encoding="utf-8")

    def __repr__(self) -> str:
        return f"Prompt({self._filepath.name})"


def __getattr__(name: str) -> Prompt:
    filepath = _PROMPTS_DIR / f"{name}.md"
    if filepath.is_file():
        return Prompt(filepath)
    raise AttributeError(f"module 'src.brain.prompts' has no attribute '{name}'")
