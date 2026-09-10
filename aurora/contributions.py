"""项目级稳定多值贡献点；新增提供者只引用既有贡献键。"""

from collections.abc import Callable

from aurora.composer import ContributionKey
from src.contracts import Tool, TreeLauncher

TOOL_CONTRIBUTIONS = ContributionKey[Tool]("tools.catalog")

type TreeLauncherBinding = Callable[[TreeLauncher], None]

TREE_LAUNCHER_BINDINGS = ContributionKey[TreeLauncherBinding]("runtime.tree_launcher.bindings")
