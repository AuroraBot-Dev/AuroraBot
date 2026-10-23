"""内容资源存储的独立配置。"""

from dataclasses import dataclass

from aurora_bot.utils.validation import check_relative_directory


@dataclass(frozen=True, slots=True)
class ArtifactsConfig:
    """所有资源版本保存在项目内的持久目录。"""

    directory: str = "data/artifacts"

    def __post_init__(self) -> None:
        """相对路径由装配入口结合项目根目录解释。"""
        check_relative_directory(self.directory, "artifacts.directory")
