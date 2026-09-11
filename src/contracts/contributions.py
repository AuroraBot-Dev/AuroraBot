"""项目级稳定多值贡献点；内置能力与第三方插件只引用既有贡献键。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from src.contracts.kernel import ContributionKey
from src.contracts.tool import Tool

if TYPE_CHECKING:
    from src.contracts.agent import TreeLauncher


class TreeLauncherBinding(Protocol):
    """把已构造的 TreeLauncher 接入某个运行期端口的同步绑定函数。"""

    def __call__(self, launcher: TreeLauncher) -> None: ...


TOOL_CONTRIBUTIONS = ContributionKey[Tool]("tools.catalog")

TREE_LAUNCHER_BINDINGS = ContributionKey[TreeLauncherBinding]("runtime.tree_launcher.bindings")
