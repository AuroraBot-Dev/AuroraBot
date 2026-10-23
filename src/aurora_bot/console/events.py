"""``aurora_bot.console`` 提交到世界线的事件 kind 与 scope。"""

from __future__ import annotations

from aurora_bot.contracts.identity import world_scope

CONSOLE_SCOPE = f"{world_scope('aurora')}/console"
CONSOLE_INPUT = "console.input"
