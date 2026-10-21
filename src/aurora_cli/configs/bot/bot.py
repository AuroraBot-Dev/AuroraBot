"""解析当前进程所属的 Bot 身份。"""

from __future__ import annotations

from aurora_bot.bot.config import BotConfig
from aurora_cli.contracts.config import ConfigSpec, TableShape, text_field

CONFIG_SPEC = ConfigSpec[BotConfig](
    name="bot",
    path="config/bot.toml",
    shape=TableShape(path=("bot",), fields=(text_field("bot_id"),), model=BotConfig),
)
