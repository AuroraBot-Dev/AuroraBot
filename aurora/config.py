"""把显式注册的项目配置合并为一个只读配置对象。"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class ConfigKey[T]:
    """为一个配置值提供稳定且可类型化的名称。"""

    name: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("配置键名称不能为空")


@dataclass(frozen=True, slots=True)
class AuroraConfig:
    """包含全部已注册配置值的只读集合。"""

    _values: Mapping[ConfigKey[object], object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "_values", MappingProxyType(dict(self._values)))

    def get[T](self, key: ConfigKey[T]) -> T:
        try:
            value = self._values[cast("ConfigKey[object]", key)]
        except KeyError as error:
            raise KeyError(f"配置尚未注册：{key.name}") from error
        return cast("T", value)

    def with_value[T](self, key: ConfigKey[T], value: T) -> AuroraConfig:
        values = dict(self._values)
        stored_key = cast("ConfigKey[object]", key)
        if stored_key not in values:
            raise KeyError(f"不能替换尚未注册的配置：{key.name}")
        values[stored_key] = value
        return AuroraConfig(values)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(key.name for key in self._values)


class ConfigCollector:
    """接收配置模块注册，并在注册时读取对应 TOML。"""

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root
        self._values: dict[ConfigKey[object], object] = {}
        self._names: set[str] = set()

    def register[T](self, key: ConfigKey[T], relative_path: str, parser: Callable[[Path], T]) -> None:
        if key.name in self._names:
            raise ValueError(f"配置重复注册：{key.name}")
        self._names.add(key.name)
        self._values[cast("ConfigKey[object]", key)] = parser(self._project_root / relative_path)

    def build(self) -> AuroraConfig:
        return AuroraConfig(self._values)


type ConfigRegistrar = Callable[[ConfigCollector], None]


def collect_config(project_root: Path, registrars: Iterable[ConfigRegistrar]) -> AuroraConfig:
    """按显式注册顺序读取配置并生成统一配置对象。"""
    collector = ConfigCollector(project_root)
    for register in registrars:
        register(collector)
    return collector.build()
