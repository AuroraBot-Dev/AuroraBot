"""将输入简写转换为已有 JSON 请求，模块调用仍经过同一校验入口。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from playground.session import failure, reject_constant

if TYPE_CHECKING:
    from playground.session import Session

HELP = (
    "list · 列出模块",
    "use <模块> · 选择当前模块",
    "describe [模块或模块.操作] · 查看格式；选中模块后也可只写操作名",
    '<模块>.<操作> {"参数": "值"} · 调用操作；选中模块后可省略模块名，无参数可省略 JSON',
    "help · 查看输入方式",
    "exit / quit · 退出",
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
            raise ValueError("请输入命令或 JSON 请求；help 查看输入方式。")
        name, tail = parts[0], parts[1] if len(parts) > 1 else ""
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
                raise ValueError("模块不存在；list 查看可用模块。")
            self.module = tail
            return {"ok": True, "result": {"module": tail}}
        if name == "describe":
            target = tail or self.module
            if target is None:
                raise ValueError("请指定模块，或先 use <模块>。")
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
            raise ValueError("请使用 <模块>.<操作>，或先 use <模块>；help 查看输入方式。")
        return module, operation

    def suggestions(self, text: str) -> list[str]:
        candidates = ["help", "list", "use ", "describe ", "exit", "quit"]
        candidates.extend(f"use {module}" for module in self.session.modules)
        candidates.extend(f"describe {module}" for module in self.session.modules)
        candidates.extend(f"{module}." for module in self.session.modules)
        for module in self.session.modules:
            if module != self.module and not text.startswith((f"{module}.", f"describe {module}.")):
                continue
            try:
                operations = self.session.operations(module)
            except (ValueError, TypeError):
                continue
            for operation in operations:
                candidates.extend((f"{module}.{operation}", f"describe {module}.{operation}"))
                if module == self.module:
                    candidates.extend((operation, f"describe {operation}"))
        return sorted({candidate for candidate in candidates if candidate.startswith(text) and candidate != text})
