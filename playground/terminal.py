"""终端编辑和输出格式；管道默认保持一行请求、一行 JSON 响应。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.input import create_input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.output import create_output

from playground.commands import Commands
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
        for suggestion in self.commands.suggestions(text):
            yield Completion(suggestion, start_position=-len(text))


def create_editor(commands: Commands, input_stream: Input, output_stream: Output) -> PromptSession[str]:
    bindings = KeyBindings()

    @bindings.add("enter")
    def enter(event: KeyPressEvent) -> None:
        if needs_more_input(event.current_buffer.text):
            event.current_buffer.insert_text("\n")
        else:
            event.current_buffer.validate_and_handle()

    return PromptSession(
        input=input_stream,
        output=output_stream,
        history=InMemoryHistory(),
        completer=CommandCompleter(commands),
        complete_while_typing=False,
        multiline=True,
        prompt_continuation="... ",
        key_bindings=bindings,
    )


def read_request(stdin: TextIO, editor: PromptSession[str] | None, module: str | None) -> str:
    if editor is not None:
        return editor.prompt(f"{module or 'json'}> ")
    line = stdin.readline()
    if not line:
        raise EOFError
    return line


def interact(stdin: TextIO, stdout: TextIO, stderr: TextIO, *, pretty: bool = False, module: str | None = None) -> int:
    commands = Commands(Session())

    def write(response: object) -> None:
        stdout.write(json.dumps(response, ensure_ascii=False, allow_nan=False, indent=2 if pretty else None) + "\n")
        stdout.flush()

    if module is not None:
        selected = commands.handle(f"use {module}")
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
            stderr.write(
                "Aurora Playground · JSON 或简写命令；help 查看用法\n"
                "list → use <模块> → describe → <操作> {参数 JSON}\n"
                "Tab 补全，↑/↓ 历史；JSON 未闭合时回车续行。\n"
                "exit / Ctrl+D 退出；Ctrl+C 中断。\n"
            )
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
