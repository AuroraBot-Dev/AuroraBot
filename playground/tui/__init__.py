"""Textual 模块调试界面；操作声明、输入校验和状态归属均复用 Session。"""

from __future__ import annotations

import json
import shlex
import sys
from typing import TYPE_CHECKING, Any, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Footer, Static, TabbedContent, TabPane, TextArea
from textual.worker import Worker, WorkerState

from playground.rendering import formatted, highlighted
from playground.session import Session, failure, reject_constant
from playground.tui.backend import Backend
from playground.tui.picker import Picker

if TYPE_CHECKING:
    from rich.text import Text
    from textual.events import Unmount


class JsonArea(TextArea):
    """使用 Rich 高亮，无需额外的语法解析器，保留文本选择和复制能力。"""

    highlight_json = True
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter", "submit_command", show=False, priority=True),
        Binding("tab", "complete_command", show=False, priority=True),
    ]

    class CommandSubmitted(Message):
        pass

    class CommandCompletionRequested(Message):
        pass

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in {"submit_command", "complete_command"}:
            return not self.read_only and self.text.lstrip().startswith("/")
        return super().check_action(action, parameters)

    def action_submit_command(self) -> None:
        self.post_message(self.CommandSubmitted())

    def action_complete_command(self) -> None:
        self.post_message(self.CommandCompletionRequested())

    def get_line(self, line_index: int) -> Text:
        line = super().get_line(line_index)
        return highlighted(line.plain) if self.highlight_json else line


class PlaygroundApp(App[None]):
    TITLE = "Aurora Playground"
    CSS_PATH = "app.tcss"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("f5,ctrl+enter", "execute", "执行", priority=True),
        Binding("ctrl+k", "modules", "模块", priority=True),
        Binding("ctrl+p", "commands", "命令", priority=True),
        Binding("ctrl+o", "operations", "操作", priority=True),
        Binding("ctrl+r", "example", "示例", priority=True),
        Binding("ctrl+q", "quit", "退出", priority=True),
    ]

    def __init__(self, *, module: str | None = None, session: Session | None = None, pretty: bool = True) -> None:
        super().__init__()
        self.theme = "textual-dark"
        session = session if session is not None else Session()
        if module is not None and module not in session.modules:
            session.close()
            raise ValueError(f"模块不存在：{module}")
        self.backend = Backend(session)
        self.pretty = pretty
        self.module = module or next(iter(session.modules), None)
        self.operation: str | None = None
        self.module_button = Button(self.module or "选择模块", id="module")
        self.operation_button = Button("选择操作", id="operation", disabled=True)
        self.description = Static("", id="description", markup=False)
        self.input_caption = Static("参数 · JSON", classes="caption")
        self.input_editor = JsonArea("{}", id="input", tab_behavior="focus")
        self.output_editor = JsonArea("尚未执行操作。", id="output", read_only=True, tab_behavior="focus")
        self.schema_editor = JsonArea("", id="schema", read_only=True, tab_behavior="focus")
        for editor in (self.input_editor, self.output_editor, self.schema_editor):
            editor.highlight_json = pretty
        self.execute_button = Button("执行 ↵", id="execute", disabled=True)
        self.status = Static("就绪", id="status", markup=False)
        self.tabs = TabbedContent(id="results")
        self._operations: dict[str, dict[str, Any]] = {}
        self._busy = False

    @property
    def is_command(self) -> bool:
        return (self.module, self.operation) == ("cli", "execute")

    def compose(self) -> ComposeResult:
        with Horizontal(id="toolbar"):
            yield Static("AURORA  / playground", id="brand")
            yield self.module_button
            yield self.operation_button
        yield self.description
        with Vertical(id="workspace"):
            with self.tabs:
                with TabPane("结果", id="response"):
                    yield self.output_editor
                with TabPane("接口说明", id="documentation"):
                    yield self.schema_editor
            with Vertical(id="request"):
                yield self.input_caption
                yield self.input_editor
                with Horizontal(id="actions"):
                    yield self.status
                    yield self.execute_button
        yield Footer()

    async def on_mount(self) -> None:
        await self.select_module(self.module)
        self.input_editor.focus()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area is self.input_editor and self.input_editor.text == "/":
            self.action_commands()

    def on_json_area_command_submitted(self) -> None:
        self.action_execute()

    def on_json_area_command_completion_requested(self) -> None:
        self.action_commands()

    def action_commands(self) -> None:
        if self._busy or isinstance(self.screen, Picker):
            return
        text = self.input_editor.text.strip()
        choices = self.backend.commands.command_choices()
        if text.startswith(("/use ", "/describe ")):
            choices = dict(self.backend.commands.completions(text))
        self.push_screen(
            Picker(
                "命令",
                [(name, f"{name}  {description}") for name, description in choices.items()],
                None,
                query=text.removeprefix("/") if text.startswith("/") else "",
            ),
            self.complete_command,
        )

    def complete_command(self, command: str | None) -> None:
        if command is not None:
            self.input_editor.load_text(command + (" " if command in {"/use", "/describe", "/aurora"} else ""))
            self.input_editor.move_cursor(self.input_editor.document.end)
        self.input_editor.focus()

    def action_modules(self) -> None:
        if self._busy or isinstance(self.screen, Picker) or not self.backend.session.modules:
            return
        choices = [(name, f"{name}  {spec.description}") for name, spec in self.backend.session.modules.items()]
        self.push_screen(Picker("选择模块", choices, self.module), self.select_module)

    def action_operations(self) -> None:
        if self._busy or isinstance(self.screen, Picker) or not self._operations:
            return
        choices = [(name, f"{name}  {spec['description']}") for name, spec in self._operations.items()]
        self.push_screen(Picker("选择操作", choices, self.operation), self.select_operation)

    async def select_module(self, module: str | None) -> None:
        if module is None:
            self.set_busy(False)
            return
        if module == self.module and self._operations:
            return
        self.module, self.operation = module, None
        self.backend.commands.module = module
        self.module_button.label = module
        self.operation_button.label = "选择操作"
        self.description.update("")
        self.schema_editor.load_text("")
        self._operations.clear()
        self.set_busy(True)
        try:
            response = await self.backend.request(json.dumps({"action": "describe", "module": module}))
            if not response["ok"]:
                self.show_response(response)
                self.description.update("无法读取操作说明。")
                return
            self._operations = {item["operation"]: item for item in response["result"]["operations"]}
            self.select_operation(next(iter(self._operations), None))
            if not self._operations:
                self.description.update("该模块没有可用操作。")
                self.input_editor.load_text("{}")
        finally:
            self.set_busy(False)

    def select_operation(self, operation: str | None) -> None:
        if operation is None or operation not in self._operations:
            return
        self.operation = operation
        self.operation_button.label = operation
        spec = self._operations[operation]
        self.description.update(spec["description"])
        self.schema_editor.load_text(formatted(spec, pretty=self.pretty))
        self.input_caption.update("命令 · aurora" if self.is_command else "参数 · JSON")
        self.input_editor.highlight_json = self.pretty and not self.is_command
        self.load_example()
        self.set_busy(self._busy)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.module_button.disabled = busy or not bool(self.backend.session.modules)
        self.operation_button.disabled = busy or not bool(self._operations)
        self.input_editor.disabled = busy
        self.execute_button.disabled = busy or self.operation is None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button is self.execute_button:
            self.action_execute()
        elif event.button is self.module_button:
            self.action_modules()
        elif event.button is self.operation_button:
            self.action_operations()

    def action_example(self) -> None:
        if self._busy or self.operation is None or isinstance(self.screen, Picker):
            return
        self.load_example()

    def load_example(self) -> None:
        if self.operation is None:
            return
        example = self._operations[self.operation]["example"]["input"]
        if self.is_command:
            content = example.get("command") or shlex.join(["aurora", *example.get("argv", [])])
        else:
            content = formatted(example, pretty=self.pretty)
        self.input_editor.load_text(content)
        self.input_editor.focus()

    def action_execute(self) -> None:
        if self._busy or isinstance(self.screen, Picker):
            return
        text = self.input_editor.text.strip()
        if text == "/use":
            self.action_modules()
            return
        try:
            request = self.encode_request(text)
        except (ValueError, RecursionError):
            self.show_response(failure("invalid_json", "请输入有效的参数 JSON 对象。"))
            return
        if request is None:
            return
        self.set_busy(True)
        self.status.update("执行中…")
        self.run_worker(self.execute(request), group="operation", exit_on_error=False)

    def encode_request(self, text: str) -> str | None:
        if text.startswith("/"):
            return text
        if self.operation is None:
            return None
        arguments = {"command": text} if self.is_command else json.loads(text, parse_constant=reject_constant)
        return formatted({"module": self.module, "operation": self.operation, "input": arguments})

    async def execute(self, request: str) -> None:
        try:
            response = await self.backend.request(request)
            if self.backend.session.closed:
                self.exit()
                return
            if self.backend.commands.module != self.module:
                await self.select_module(self.backend.commands.module)
            self.show_response(response)
        finally:
            self.set_busy(False)
            self.input_editor.focus()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state is WorkerState.ERROR:
            self.show_response(
                failure("execution_error", "操作执行异常。", {"type": type(event.worker.error).__name__})
            )

    def show_response(self, response: dict[str, Any]) -> None:
        self.output_editor.load_text(formatted(response, pretty=self.pretty))
        self.tabs.active = "response"
        result = response.get("result", {})
        if response["ok"] and isinstance(result, dict) and "exit_code" in result:
            self.status.update(f"退出码 {result['exit_code']}" + (" · 超时" if result.get("timed_out") else ""))
        else:
            self.status.update("已完成" if response["ok"] else "请求失败")

    async def on_unmount(self, event: Unmount) -> None:
        await self.backend.close()


def run(*, module: str | None = None, pretty: bool = True) -> int:
    try:
        app = PlaygroundApp(module=module, pretty=pretty)
    except (ValueError, TypeError) as error:
        sys.stderr.write(f"无法启动 Playground：{error}\n")
        return 2
    app.run()
    return 0
