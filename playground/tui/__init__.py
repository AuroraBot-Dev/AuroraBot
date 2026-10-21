"""Textual 模块调试界面；操作声明、输入校验和状态归属均复用 Session。"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Select, Static, TabbedContent, TabPane, TextArea
from textual.worker import Worker, WorkerState

from playground.session import Session, failure, reject_constant
from playground.tui.backend import Backend

if TYPE_CHECKING:
    from textual.events import Unmount


def formatted(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)


class PlaygroundApp(App[None]):
    TITLE = "Aurora Playground"
    CSS_PATH = "app.tcss"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("f5,ctrl+enter", "execute", "执行", priority=True),
        Binding("ctrl+r", "example", "载入示例", priority=True),
        Binding("ctrl+q", "quit", "退出", priority=True),
    ]

    def __init__(self, *, module: str | None = None, session: Session | None = None) -> None:
        super().__init__()
        session = session if session is not None else Session()
        if module is not None and module not in session.modules:
            session.close()
            raise ValueError(f"模块不存在：{module}")
        self.backend = Backend(session)
        selected = module or next(iter(session.modules), Select.NULL)
        self.module_select = Select(
            [(name, name) for name in session.modules],
            value=selected,
            prompt="选择模块",
            id="module",
            allow_blank=not bool(session.modules),
        )
        self.operation_select: Select[str] = Select([], prompt="选择操作", id="operation", disabled=True)
        self.description = Static("正在读取操作说明…", id="description", markup=False)
        self.input_editor = TextArea("{}", id="input", show_line_numbers=True, tab_behavior="focus")
        self.output_editor = TextArea("尚未执行操作。", id="output", read_only=True, tab_behavior="focus")
        self.schema_editor = TextArea("", id="schema", read_only=True, tab_behavior="focus")
        self.execute_button = Button("执行", id="execute", variant="primary", disabled=True)
        self.example_button = Button("载入示例", id="example", disabled=True)
        self.status = Static("就绪", id="status", markup=False)
        self.tabs = TabbedContent(id="results")
        self._operations: dict[str, dict[str, Any]] = {}
        self._loaded_module: str | None = None
        self._selected: tuple[str, str] | None = None
        self._busy = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="selectors"):
            yield self.module_select
            yield self.operation_select
        yield self.description
        with Horizontal(id="workspace"):
            with Vertical(id="request"):
                yield Static("输入参数 · JSON", classes="caption")
                yield self.input_editor
                with Horizontal(id="actions"):
                    yield self.execute_button
                    yield self.example_button
            with self.tabs:
                with TabPane("结果", id="response"):
                    yield self.output_editor
                with TabPane("接口说明", id="documentation"):
                    yield self.schema_editor
        yield self.status
        yield Footer()

    async def on_mount(self) -> None:
        await self.select_module()

    async def on_select_changed(self, event: Select.Changed) -> None:
        if event.select is self.module_select:
            await self.select_module()
        elif event.select is self.operation_select:
            self.select_operation()

    async def select_module(self) -> None:
        module = self.module_select.value
        if not isinstance(module, str):
            self.description.update("没有可用模块。")
            self.set_busy(False)
            return
        if module == self._loaded_module:
            return
        self._loaded_module, self._selected = module, None
        self._operations.clear()
        self.set_busy(True)
        try:
            response = await self.backend.request(json.dumps({"action": "describe", "module": module}))
            if not response["ok"]:
                self.show_response(response)
                self.description.update("无法读取该模块的操作说明。")
                self.operation_select.set_options([])
                return
            self._operations = {item["operation"]: item for item in response["result"]["operations"]}
            self.operation_select.set_options((name, name) for name in self._operations)
            self.operation_select.value = next(iter(self._operations), Select.NULL)
            self.select_operation()
        finally:
            self.set_busy(False)

    def select_operation(self) -> None:
        module, operation = self.module_select.value, self.operation_select.value
        if not isinstance(module, str) or not isinstance(operation, str) or operation not in self._operations:
            self._selected = None
            self.description.update("请选择操作。" if self._operations else "该模块没有可用操作。")
            self.schema_editor.load_text("")
            self.input_editor.load_text("{}")
            self.set_busy(self._busy)
            return
        if self._selected == (module, operation):
            return
        self._selected = module, operation
        spec = self._operations[operation]
        self.description.update(f"{module}.{operation} · {spec['description']}")
        self.schema_editor.load_text(formatted(spec))
        self.input_editor.load_text(formatted(spec["example"]["input"]))
        self.status.update("编辑参数后执行；切换操作只载入说明和示例。")
        self.set_busy(self._busy)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.module_select.disabled = busy or not bool(self.backend.session.modules)
        self.operation_select.disabled = busy or not bool(self._operations)
        self.input_editor.disabled = busy
        self.execute_button.disabled = busy or self._selected is None
        self.example_button.disabled = busy or self._selected is None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button is self.execute_button:
            self.action_execute()
        elif event.button is self.example_button:
            self.action_example()

    def action_example(self) -> None:
        if self._busy or self._selected is None:
            return
        self.input_editor.load_text(formatted(self._operations[self._selected[1]]["example"]["input"]))
        self.input_editor.focus()

    def action_execute(self) -> None:
        if self._busy or self._selected is None:
            return
        module, operation = self._selected
        try:
            arguments = json.loads(self.input_editor.text, parse_constant=reject_constant)
            request = formatted({"module": module, "operation": operation, "input": arguments})
        except (ValueError, RecursionError):
            self.show_response(failure("invalid_json", "请输入有效的参数 JSON 对象。"))
            return
        self.set_busy(True)
        self.status.update(f"正在执行 {module}.{operation}…")
        self.run_worker(self.execute(request), group="operation", exit_on_error=False)

    async def execute(self, request: str) -> None:
        try:
            self.show_response(await self.backend.request(request))
        finally:
            self.set_busy(False)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state is WorkerState.ERROR:
            self.show_response(
                failure("execution_error", "操作执行异常。", {"type": type(event.worker.error).__name__})
            )

    def show_response(self, response: dict[str, Any]) -> None:
        self.output_editor.load_text(formatted(response))
        self.tabs.active = "response"
        self.status.update("已返回结果。" if response["ok"] else "请求失败；可修改参数后重新执行。")

    async def on_unmount(self, event: Unmount) -> None:
        await self.backend.close()


def run(*, module: str | None = None) -> int:
    try:
        app = PlaygroundApp(module=module)
    except (ValueError, TypeError) as error:
        sys.stderr.write(f"无法启动 Playground：{error}\n")
        return 2
    app.run()
    return 0
