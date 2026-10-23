"""带过滤输入的模态选择器；选择只改变编辑目标，不执行操作。"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.events import Key


class Picker(ModalScreen[str | None]):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "关闭", priority=True),
        Binding("tab", "confirm", "补全", priority=True),
    ]

    def __init__(self, title: str, choices: list[tuple[str, str]], selected: str | None, *, query: str = "") -> None:
        super().__init__()
        self.title_text = title
        self.choices = choices
        self.selected = selected
        self.query_text = query

    def compose(self) -> ComposeResult:
        with Vertical(id="picker"):
            yield Static(self.title_text, id="picker-title", markup=False)
            yield Input(value=self.query_text, placeholder="搜索…", id="picker-search")
            yield OptionList(id="picker-options", markup=False)
            yield Static("↑ ↓ 选择    Tab / Enter 确认    Esc 关闭", id="picker-hint")

    def on_mount(self) -> None:
        self.filter_options(self.query_text)
        self.query_one(Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self.filter_options(event.value)

    def filter_options(self, query: str) -> None:
        options = self.query_one(OptionList)
        options.clear_options()
        choices = [(key, label) for key, label in self.choices if query.casefold() in label.casefold()]
        options.add_options(Option(Text(label), id=key) for key, label in choices)
        if choices:
            options.highlighted = next((i for i, (key, _) in enumerate(choices) if key == self.selected), 0)

    def on_key(self, event: Key) -> None:
        if event.key in {"up", "down"}:
            options = self.query_one(OptionList)
            if event.key == "up":
                options.action_cursor_up()
            else:
                options.action_cursor_down()
            event.stop()
            event.prevent_default()

    def on_input_submitted(self) -> None:
        self.action_confirm()

    def action_confirm(self) -> None:
        options = self.query_one(OptionList)
        if options.highlighted is not None:
            self.dismiss(options.get_option_at_index(options.highlighted).id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)
