"""将斜杠命令转换为已有 JSON 请求，模块调用仍经过同一校验入口。"""

from __future__ import annotations

import json
import shlex
from typing import TYPE_CHECKING, Any

from playground.session import failure, reject_constant

if TYPE_CHECKING:
    from playground.session import Session

BUILTINS = {
    "/help": "查看用法",
    "/list": "列出模块",
    "/use": "选择模块",
    "/describe": "查看模块或操作说明",
    "/aurora": "执行真实 CLI 命令",
    "/exit": "退出",
    "/quit": "退出",
}

HELP = (
    "/list · 列出模块",
    "/use <模块> · 选择当前模块",
    "/describe [模块或模块.操作] · 查看格式；选中模块后也可只写操作名",
    '/<模块>.<操作> {"参数": "值"} · 调用操作；选中模块后可省略模块名，无参数可省略 JSON',
    "/aurora <参数> · 执行真实 CLI 命令；读取项目配置和插件，可能产生实际效果",
    "/help · 查看输入方式",
    "/exit /quit · 退出",
)


class Commands:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.module: str | None = None

    def handle(self, text: str) -> dict[str, Any]:
        text = text.strip()
        if text.startswith(("{", "[")):
            return self.session.handle(text)
        try:
            request = self.request(text)
            encoded = json.dumps(request, ensure_ascii=False, allow_nan=False)
        except (ValueError, RecursionError) as error:
            return failure("invalid_command", str(error))
        if "ok" in request:
            return request
        return self.session.handle(encoded)

    def request(self, text: str) -> dict[str, Any]:
        parts = text.split(maxsplit=1)
        if not parts:
            raise ValueError("请输入命令或 JSON 请求；/help 查看输入方式。")
        name, tail = parts[0].removeprefix("/"), parts[1] if len(parts) > 1 else ""
        if name == "aurora":
            return {"module": "cli", "operation": "execute", "input": {"argv": shlex.split(tail)}}
        if name in {"list", "exit", "quit", "help"}:
            if tail:
                raise ValueError(f"{name} 不接受参数。")
            return (
                {"ok": True, "result": {"commands": HELP}}
                if name == "help"
                else {"action": "exit" if name == "quit" else name}
            )
        if name == "use":
            if tail not in self.session.modules:
                raise ValueError("模块不存在；/list 查看可用模块。")
            self.module = tail
            return {"ok": True, "result": {"module": tail}}
        if name == "describe":
            target = tail.removeprefix("/") or self.module
            if target is None:
                raise ValueError("请指定模块，或先 /use <模块>。")
            if target in self.session.modules:
                return {"action": "describe", "module": target}
            module, operation = self.target(target)
            return {"action": "describe", "module": module, "operation": operation}
        module, operation = self.target(name)
        arguments = json.loads(tail, parse_constant=reject_constant) if tail else {}
        return {"module": module, "operation": operation, "input": arguments}

    def target(self, text: str) -> tuple[str, str]:
        if "." in text:
            module, operation = text.rsplit(".", 1)
        elif self.module is not None:
            module, operation = self.module, text
        else:
            raise ValueError("请使用 /<模块>.<操作>，或先 /use <模块>；/help 查看输入方式。")
        return module, operation

    def command_choices(self) -> dict[str, str]:
        choices = dict(BUILTINS)
        for module in self.session.modules:
            try:
                operations = self.session.operations(module)
            except (ValueError, TypeError):
                continue
            for operation in operations.values():
                choices[f"/{module}.{operation.name}"] = operation.description
                if module == self.module:
                    choices.setdefault(f"/{operation.name}", operation.description)
        return choices

    def completions(self, text: str) -> list[tuple[str, str]]:
        slash = text.startswith("/")
        query = text if slash else f"/{text}"
        if query.startswith("/use "):
            choices = {f"/use {name}": module.description for name, module in self.session.modules.items()}
        elif query.startswith("/describe "):
            choices = {f"/describe {name}": module.description for name, module in self.session.modules.items()}
            choices.update(
                (f"/describe {name[1:]}", description)
                for name, description in self.command_choices().items()
                if name not in BUILTINS
            )
        else:
            choices = self.command_choices()
        matched = [
            (name if slash else name[1:], description)
            for name, description in choices.items()
            if name != query and (name.startswith(query) or (slash and query[1:].casefold() in name[1:].casefold()))
        ]
        return sorted(matched, key=lambda item: (not item[0].startswith(text), item[0]))

    def suggestions(self, text: str) -> list[str]:
        return [name for name, _description in self.completions(text)]
