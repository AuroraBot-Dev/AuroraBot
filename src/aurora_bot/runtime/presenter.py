"""按节点增量渲染 认知消息到终端输出。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.markup import escape as markup_escape

from aurora_bot.utils import bounded_summary

if TYPE_CHECKING:
    from collections.abc import Callable

    from aurora_bot.contracts import AgentNode, ChatMessage


class CognitionTextPresenter:
    """把 执行器的节点消息增量渲染为终端文本；不持有认知状态。"""

    def __init__(self, output: Callable[[str], None] = print) -> None:
        self._output = output
        self._printed: dict[str, int] = {}

    def echo(self, nodes: tuple[AgentNode, ...]) -> None:
        """只渲染每个节点自上次以来新增的消息。"""
        console = Console(highlight=False) if self._output is print else None
        for node in nodes:
            seen = self._printed.get(node.node_id, 0)
            for message in node.messages[seen:]:
                self._echo_message(node, message, console)
            self._printed[node.node_id] = len(node.messages)

    def _echo_message(self, node: AgentNode, message: ChatMessage, console: Console | None) -> None:
        tag = node.definition_id
        if message.role == "assistant":
            if message.content.strip():
                self._echo_line("Cadence>", tag, message.content, console)
            for call in message.tool_calls:
                self._echo_line("→", tag, call.name, console, indent=True)
        elif message.role == "tool":
            summary = bounded_summary((message.content,))
            label = "失败" if message.is_error else "←"
            self._echo_line(label, tag, summary, console, indent=True)

    def _echo_line(
        self,
        prefix: str,
        tag: str,
        content: str,
        console: Console | None,
        *,
        indent: bool = False,
    ) -> None:
        marker = f"{'  ' if indent else ''}{prefix}"
        if console is None:
            self._output(f"{marker} [{tag}] {content}")
            return
        console.print(
            f"[bold]{marker}[/bold] [cyan]\\[{markup_escape(tag)}][/cyan] {markup_escape(content)}",
            highlight=False,
        )
