"""配置组合根：合并显式注册的项目配置成一个只读配置对象。"""

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
class ConfigSource:
    """记录一个注册配置的名称与项目相对路径。"""

    name: str
    relative_path: str


@dataclass(frozen=True, slots=True)
class TomlDocument:
    """尚未进入运行组合的只读 TOML 文档。"""

    values: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


@dataclass(frozen=True, slots=True)
class AuroraConfig:
    """包含全部已注册配置值的只读集合。"""

    _values: Mapping[ConfigKey[object], object]
    _sources: tuple[ConfigSource, ...] = ()
    _project_root: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "_values", MappingProxyType(dict(self._values)))
        if self._project_root is not None:
            object.__setattr__(self, "_project_root", self._project_root.resolve())

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
        return AuroraConfig(values, self._sources, self._project_root)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(key.name for key in self._values)

    @property
    def sources(self) -> tuple[ConfigSource, ...]:
        return self._sources

    @property
    def project_root(self) -> Path:
        if self._project_root is None:
            raise RuntimeError("配置没有关联项目根目录")
        return self._project_root

    def source(self, name: str) -> ConfigSource:
        for source in self._sources:
            if source.name == name:
                return source
        raise KeyError(f"配置尚未注册：{name}")


class ConfigCollector:
    """接收配置模块注册，并在注册时读取对应 TOML。"""

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root
        self._values: dict[ConfigKey[object], object] = {}
        self._names: set[str] = set()
        self._paths: set[str] = set()
        self._sources: list[ConfigSource] = []

    def register[T](self, key: ConfigKey[T], relative_path: str, parser: Callable[[Path], T]) -> None:
        if key.name in self._names:
            raise ValueError(f"配置重复注册：{key.name}")
        if relative_path in self._paths:
            raise ValueError(f"配置文件重复注册：{relative_path}")
        self._names.add(key.name)
        self._paths.add(relative_path)
        self._sources.append(ConfigSource(key.name, relative_path))
        self._values[cast("ConfigKey[object]", key)] = parser(self._project_root / relative_path)

    def build(self) -> AuroraConfig:
        return AuroraConfig(self._values, tuple(self._sources), self._project_root)


type ConfigRegistrar = Callable[[ConfigCollector], None]


def collect_config(project_root: Path, registrars: Iterable[ConfigRegistrar]) -> AuroraConfig:
    """按显式注册顺序读取配置并生成统一配置对象。"""
    collector = ConfigCollector(project_root)
    for register in registrars:
        register(collector)
    return collector.build()
