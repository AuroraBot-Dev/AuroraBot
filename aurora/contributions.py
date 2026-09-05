"""项目级稳定多值贡献点；新增提供者只引用既有贡献键。"""

from aurora.composer import ContributionKey
from src.contracts import Tool

TOOL_CONTRIBUTIONS = ContributionKey[Tool]("tools.catalog")
