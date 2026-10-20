"""组合内核使用的公共值类型与配置访问端口。

贡献键是稳定公共事实：内置能力与第三方插件都向同一键追加同类型值。
``Settings`` 是模块读取自身配置的只读入口；具体 TOML 解析与配置形状由项目层提供。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class ContributionKey[T]:
    """标识一个允许多个模块追加同类型值的稳定贡献点。"""

    name: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("贡献键名称不能为空")


class Settings(Protocol):
    """按配置 DTO 类型读取只读配置值，并暴露项目根目录。"""

    @property
    def project_root(self) -> Path: ...

    def resolve[T](self, config_type: type[T]) -> T: ...
