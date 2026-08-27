"""Panel 启动后的本地凭据提示。"""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel

if TYPE_CHECKING:
    from ops.panel.contracts import PanelSettings
    from ops.panel.store import PanelStore


@cache
def _default_console() -> Console:
    return Console(highlight=False)


def print_panel_notice(
    settings: PanelSettings,
    store: PanelStore,
    *,
    console: Console | None = None,
) -> None:
    output = console if console is not None else _default_console()
    output.print(f"Panel 后端已启动：{_display_url(settings)}（profile: {settings.profile}）")
    if store.token_created:
        content = (
            f"[bold yellow]Token:[/bold yellow] [bold green]{escape(store.bootstrap_token)}[/bold green]\n\n"
            "[dim]请妥善保管 Token。\n"
            f"你也可以在 [bold]{escape(str(store.token_path))}[/bold] 查看你的 Token。\n"
            "如果不慎泄露，请删除 Token.txt 以重新生成。[/dim]"
        )
        output.print(Panel(content, title="Aurora Panel Auth"))
    else:
        output.print(f"登录 Token 请查看：{store.token_path}")


def _display_url(settings: PanelSettings) -> str:
    display_host = "127.0.0.1" if settings.host in {"0.0.0.0", "::"} else settings.host
    if ":" in display_host and not display_host.startswith("["):
        display_host = f"[{display_host}]"
    return f"http://{display_host}:{settings.port}"
