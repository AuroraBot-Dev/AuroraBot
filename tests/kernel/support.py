"""组合内核测试共用的契约占位与无 I/O 配置入口。"""

from pathlib import Path
from typing import cast


class Alpha:
    pass


class Beta:
    pass


class Gamma:
    pass


class Settings:
    def __init__(self, values: dict[type, object] | None = None) -> None:
        self._values = values or {}

    @property
    def project_root(self) -> Path:
        return Path()

    def resolve[T](self, config_type: type[T]) -> T:
        return cast("T", self._values[config_type])


class NoConfigSettings:
    """任何配置读取均失败，用于验证失选提供方没有准备效果。"""

    @property
    def project_root(self) -> Path:
        return Path()

    def resolve[T](self, config_type: type[T]) -> T:
        raise AssertionError("不应读取项目配置")
