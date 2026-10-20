"""Bot 长期身份配置。"""

from dataclasses import dataclass

from aurorabot.contracts.identity import Identifier


@dataclass(frozen=True, slots=True)
class BotConfig:
    """指定当前进程服务的持久主体。"""

    bot_id: str

    def __post_init__(self) -> None:
        """保证 Bot 身份落在独立资源类别下。"""
        identifier = Identifier.parse(self.bot_id)
        if not identifier.path.startswith("bot/"):
            raise ValueError("Bot 身份必须形如 <namespace>:bot/<name>")
