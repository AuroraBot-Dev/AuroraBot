from __future__ import annotations

from aurora.main import run


def test_bare_cli_and_about_are_non_effectful() -> None:
    assert run([]) == 0
    assert run(["about"]) == 0
