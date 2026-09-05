from __future__ import annotations

import asyncio
from io import StringIO
from typing import TYPE_CHECKING
from unittest.mock import patch

from rich.console import Console

from ops.panel import PanelSettings, PanelStore, print_panel_notice

if TYPE_CHECKING:
    from pathlib import Path


def test_panel_notice_prints_full_token_only_when_created(tmp_path: Path) -> None:
    async def initialize(store: PanelStore) -> None:
        await store.initialize()

    first = PanelStore(tmp_path, session_ttl_seconds=60, token_factory=lambda: "bootstrap-secret")
    asyncio.run(initialize(first))
    first_output = StringIO()
    print_panel_notice(
        PanelSettings(host="0.0.0.0", port=9000, profile="quality"),
        first,
        console=Console(file=first_output, highlight=False, color_system=None, width=1000),
    )
    asyncio.run(first.close())

    second = PanelStore(tmp_path, session_ttl_seconds=60)
    asyncio.run(initialize(second))
    second_output = StringIO()
    print_panel_notice(
        PanelSettings(),
        second,
        console=Console(file=second_output, highlight=False, color_system=None, width=1000),
    )
    asyncio.run(second.close())

    assert "http://127.0.0.1:9000" in first_output.getvalue()
    assert "Token:" in first_output.getvalue()
    assert "bootstrap-secret" in first_output.getvalue()
    assert str(first.token_path) in first_output.getvalue()
    assert "bootstrap-secret" not in second_output.getvalue()
    assert f"登录 Token 请查看：{second.token_path}" in second_output.getvalue()


def test_panel_notice_defaults_to_a_console_with_highlighting_disabled(tmp_path: Path) -> None:
    async def initialize(store: PanelStore) -> None:
        await store.initialize()

    store = PanelStore(tmp_path, session_ttl_seconds=60, token_factory=lambda: "bootstrap")
    asyncio.run(initialize(store))
    calls: list[tuple[str, object]] = []

    class FakeConsole:
        def __init__(self, *, highlight: bool) -> None:
            calls.append(("highlight", highlight))

        def print(self, value: object) -> None:
            calls.append(("print", value))

    with patch("ops.panel.notice._default_console", return_value=FakeConsole(highlight=False)):
        print_panel_notice(PanelSettings(), store)
    asyncio.run(store.close())

    assert calls[0] == ("highlight", False)
    assert any(kind == "print" for kind, _ in calls)
