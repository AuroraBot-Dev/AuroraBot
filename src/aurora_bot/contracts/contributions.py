"""项目级稳定多值贡献点；内置能力与第三方插件只引用既有贡献键。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from aurora_bot.contracts.kernel import ContributionKey
from aurora_bot.contracts.tool import Tool

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Awaitable, Callable

    from aurora_bot.contracts.kernel import Settings
    from aurora_bot.contracts.pkgs.runtime import CognitionLauncher


class CognitionBinding(Protocol):
    """把已构造的 CognitionLauncher 接入某个运行期端口的同步绑定函数。"""

    def __call__(self, launcher: CognitionLauncher) -> None: ...


@dataclass(frozen=True, slots=True)
class Front:
    """一个进程前台：接收停止事件并持续运行，直到停止或自行结束。"""

    run: Callable[[asyncio.Event], Awaitable[None]]
    interactive: bool = False


@dataclass(frozen=True, slots=True)
class FrontIO:
    """进程前台的文本输入/输出参数；仅交互式前台需要。"""

    readline: Callable[[str], str] | None
    output: Callable[[str], None]


class FrontContext(Protocol):
    """创建前台时的只读上下文：按需读取已装配能力与进程运行服务。"""

    @property
    def settings(self) -> Settings: ...

    def get(self, name: str) -> Any: ...

    def get_optional(self, name: str) -> Any: ...


class FrontBinding(Protocol):
    """把一个前台绑定到当前进程运行上下文。"""

    def __call__(self, context: FrontContext) -> Front: ...


TOOL_CONTRIBUTIONS = ContributionKey[Tool]("tools.catalog")

COGNITION_BINDINGS = ContributionKey[CognitionBinding]("runtime.cognition.bindings")

FRONT_BINDINGS = ContributionKey[FrontBinding]("runtime.fronts")
