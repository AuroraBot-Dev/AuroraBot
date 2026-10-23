"""终端编辑和输出格式；默认缩进并在终端高亮，紧凑模式用于 JSON Lines。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.filters import Condition
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.input import create_input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.output import create_output
from prompt_toolkit.styles import Style

from playground.commands import Commands
from playground.rendering import write_response
from playground.session import Session

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import TextIO

    from prompt_toolkit.completion import CompleteEvent
    from prompt_toolkit.document import Document
    from prompt_toolkit.input import Input
    from prompt_toolkit.key_binding import KeyPressEvent
    from prompt_toolkit.output import Output


def needs_more_input(text: str) -> bool:
    text = text.lstrip()
    if not text.startswith(("{", "[")):
        parts = text.split(maxsplit=1)
        text = parts[1] if len(parts) > 1 else ""
    if not text.startswith(("{", "[")):
        return False
    return open_container(text)


def open_container(text: str) -> bool:
    """忽略字符串内的括号；已出现不匹配括号时立即交给 JSON 校验。"""
    stack: list[str] = []
    quoted, escaped = False, False
    for character in text:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character in "{[":
            stack.append(character)
        elif character in "}]" and (not stack or stack.pop() != {"}": "{", "]": "["}[character]):
            return False
    return bool(stack)


class CommandCompleter(Completer):
    def __init__(self, commands: Commands) -> None:
        self.commands = commands

    def get_completions(self, document: Document, complete_event: CompleteEvent) -> Iterable[Completion]:
        text = document.text_before_cursor
        for suggestion, description in self.commands.completions(text):
            yield Completion(suggestion, start_position=-len(text), display_meta=description)


def create_editor(commands: Commands, input_stream: Input, output_stream: Output) -> PromptSession[str]:
    bindings = KeyBindings()

    @bindings.add("enter")
    def enter(event: KeyPressEvent) -> None:
        if needs_more_input(event.current_buffer.text):
            event.current_buffer.insert_text("\n")
        elif event.current_buffer.complete_state and event.current_buffer.complete_state.completions:
            state = event.current_buffer.complete_state
            event.current_buffer.apply_completion(state.current_completion or state.completions[0])
        else:
            event.current_buffer.validate_and_handle()

    @bindings.add("tab")
    def complete(event: KeyPressEvent) -> None:
        buffer = event.current_buffer
        if buffer.complete_state and buffer.complete_state.completions:
            state = buffer.complete_state
            buffer.apply_completion(state.current_completion or state.completions[0])
        else:
            choices = commands.completions(buffer.text)
            if len(choices) == 1:
                name, description = choices[0]
                buffer.apply_completion(Completion(name, start_position=-len(buffer.text), display_meta=description))
            else:
                buffer.start_completion(select_first=False)

    @bindings.add("escape")
    def cancel_completion(event: KeyPressEvent) -> None:
        event.current_buffer.cancel_completion()

    editor = PromptSession(
        input=input_stream,
        output=output_stream,
        history=InMemoryHistory(),
        completer=CommandCompleter(commands),
        complete_while_typing=Condition(lambda: editor.default_buffer.text.startswith("/")),
        reserve_space_for_menu=8,
        style=Style.from_dict(
            {
                "completion-menu.completion": "bg:#242424 #dedbd5",
                "completion-menu.completion.current": "bg:#3c352b #f4dfb4",
                "completion-menu.meta.completion": "bg:#242424 #8f8b83",
                "completion-menu.meta.completion.current": "bg:#3c352b #bda17a",
                "scrollbar.background": "bg:#242424",
                "scrollbar.button": "bg:#69665f",
            }
        ),
        multiline=True,
        prompt_continuation="... ",
        key_bindings=bindings,
    )
    return editor


def read_request(stdin: TextIO, editor: PromptSession[str] | None, module: str | None) -> str:
    if editor is not None:
        return editor.prompt(f"{module or 'json'}> ")
    line = stdin.readline()
    if not line:
        raise EOFError
    return line


def interact(stdin: TextIO, stdout: TextIO, stderr: TextIO, *, pretty: bool = True, module: str | None = None) -> int:
    commands = Commands(Session())

    def write(response: object) -> None:
        write_response(response, stdout, pretty=pretty)

    if module is not None:
        selected = commands.handle(f"/use {module}")
        if not selected["ok"]:
            write(selected)
            commands.session.close()
            return 2
    terminal = stdin.isatty()
    input_stream = create_input(stdin=stdin) if terminal else None
    try:
        editor = (
            create_editor(commands, input_stream, create_output(stdout=stderr)) if input_stream is not None else None
        )
        if terminal:
            stderr.write("Aurora Playground\n")
        while not commands.session.closed:
            line = read_request(stdin, editor, commands.module)
            if line.strip():
                write(commands.handle(line))
    except EOFError:
        return 0
    except KeyboardInterrupt:
        stderr.write("\n会话已中断。\n")
        return 130
    finally:
        try:
            if input_stream is not None:
                input_stream.close()
        finally:
            commands.session.close()
    return 0
