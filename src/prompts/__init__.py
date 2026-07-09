"""提示词模板模块 —— 延迟加载 ``*.md`` 文件并通过 ``__getattr__`` 暴露 ``Prompt`` 对象。

用法::

    from src.prompts import some_template
    filled = some_template.fill(var1="value1", var2="value2")
"""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


class Prompt:
    __slots__ = ("_filepath",)

    def __init__(self, filepath: Path) -> None:
        self._filepath = filepath

    def get_content(self) -> str:
        return self._filepath.read_text(encoding="utf-8")

    def fill(self, **kwargs: str) -> str:
        result = self.get_content()
        for key, value in kwargs.items():
            result = result.replace(f"$${key}$$", value)
        return result

    def __repr__(self) -> str:
        return f"Prompt({self._filepath.name})"


def __getattr__(name: str) -> Prompt:
    filepath = _PROMPTS_DIR / f"{name}.md"
    if filepath.is_file():
        return Prompt(filepath)
    raise AttributeError(f"module 'src.prompts' has no attribute '{name}'")  # noqa: TRY003
