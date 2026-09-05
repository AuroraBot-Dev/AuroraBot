"""配置组合根：按声明式规格合并项目配置成一个只读配置对象。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

from aurora.utils.toml import (
    boolean,
    load_toml,
    optional_text,
    positive_integer,
    positive_number,
    strings,
    table,
    table_array,
    text,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path

    from aurora.utils.toml import TomlTable


class FieldKind(StrEnum):
    """声明式字段类型；决定提取与基础校验。"""

    TEXT = "text"
    OPTIONAL_TEXT = "optional_text"
    STRINGS = "strings"
    BOOLEAN = "boolean"
    POSITIVE_INTEGER = "positive_integer"
    POSITIVE_NUMBER = "positive_number"
    OPTIONAL_TABLE = "optional_table"


@dataclass(frozen=True, slots=True)
class Field:
    """声明一个表内字段的类型与目标 DTO 参数。"""

    name: str
    kind: FieldKind
    target: str | None = None
    transform: Callable[..., object] | None = None


def text_field(name: str, *, target: str | None = None) -> Field:
    return Field(name, FieldKind.TEXT, target=target)


def optional_text_field(name: str, *, target: str | None = None) -> Field:
    return Field(name, FieldKind.OPTIONAL_TEXT, target=target)


def strings_field(
    name: str,
    *,
    target: str | None = None,
    transform: Callable[..., object] | None = None,
) -> Field:
    return Field(name, FieldKind.STRINGS, target=target, transform=transform)


def boolean_field(name: str, *, target: str | None = None) -> Field:
    return Field(name, FieldKind.BOOLEAN, target=target)


def positive_integer_field(name: str, *, target: str | None = None) -> Field:
    return Field(name, FieldKind.POSITIVE_INTEGER, target=target)


def positive_number_field(name: str, *, target: str | None = None) -> Field:
    return Field(name, FieldKind.POSITIVE_NUMBER, target=target)


def optional_table_field(name: str, *, target: str | None = None) -> Field:
    return Field(name, FieldKind.OPTIONAL_TABLE, target=target)


def _optional_table(item: TomlTable, key: str) -> dict[str, object]:
    value = item.get(key)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"配置字段 {key} 必须是表")
    return dict(value)


_FIELD_EXTRACTORS: dict[FieldKind, Callable[[TomlTable, str], object]] = {
    FieldKind.TEXT: text,
    FieldKind.OPTIONAL_TEXT: optional_text,
    FieldKind.STRINGS: strings,
    FieldKind.BOOLEAN: boolean,
    FieldKind.POSITIVE_INTEGER: positive_integer,
    FieldKind.POSITIVE_NUMBER: positive_number,
    FieldKind.OPTIONAL_TABLE: _optional_table,
}


def _extract_field(item: TomlTable, field: Field) -> object:
    extractor = _FIELD_EXTRACTORS.get(field.kind)
    if extractor is None:
        raise ValueError(f"不支持的字段类型：{field.kind}")
    value = extractor(item, field.name)
    if field.transform is not None:
        value = field.transform(value)
    return value


@dataclass(frozen=True, slots=True)
class TableShape[T]:
    """声明式主形状：一段表路径 + 字段集 → 一个 DTO。"""

    path: tuple[str, ...]
    fields: tuple[Field, ...]
    model: type[T]

    def extract(self, document: TomlTable) -> object:
        current = document
        for name in self.path:
            current = table(current, name)
        values = {field.target or field.name: _extract_field(current, field) for field in self.fields}
        return self.model(**values)


@dataclass(frozen=True, slots=True)
class TableArrayShape[T]:
    """声明式表数组形状：[[...]] 每项一个 DTO → 可选容器 DTO。"""

    path: tuple[str, ...]
    fields: tuple[Field, ...]
    model: type[T]
    container: Callable[[tuple[T, ...]], object] | None = None

    def extract(self, document: TomlTable) -> object:
        current = document
        for name in self.path[:-1]:
            current = table(current, name)
        raw_items = table_array(current, self.path[-1])
        items = [
            self.model(**{field.target or field.name: _extract_field(item, field) for field in self.fields})
            for item in raw_items
        ]
        result: object = tuple(items)
        if self.container is not None:
            result = self.container(result)
        return result


@dataclass(frozen=True, slots=True)
class ConfigSpec[T]:
    """一个配置文件的声明式规格；本身兼作类型化键。"""

    name: str
    path: str
    shape: TableShape[Any] | TableArrayShape[Any] | None = None
    parse: Callable[[Path], T] | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("配置名称不能为空")
        if not self.path.strip():
            raise ValueError("配置路径不能为空")
        if self.shape is None and self.parse is None:
            raise ValueError(f"{self.name} 必须声明 shape 或 parse")

    def load(self, project_root: Path) -> T:
        path = project_root / self.path
        if self.shape is not None:
            return cast("T", self.shape.extract(load_toml(path)))
        if self.parse is not None:
            return self.parse(path)
        raise ValueError(f"{self.name} 必须声明 shape 或 parse")


@dataclass(frozen=True, slots=True)
class ConfigSource:
    """记录一个注册配置的名称与项目相对路径。"""

    name: str
    relative_path: str


@dataclass(frozen=True, slots=True)
class AuroraConfig:
    """包含全部已注册配置值的只读集合。"""

    _values: Mapping[ConfigSpec[object], object]
    _sources: tuple[ConfigSource, ...] = ()
    _project_root: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "_values", MappingProxyType(dict(self._values)))
        if self._project_root is not None:
            object.__setattr__(self, "_project_root", self._project_root.resolve())

    def get[T](self, spec: ConfigSpec[T]) -> T:
        try:
            value = self._values[cast("ConfigSpec[object]", spec)]
        except KeyError as error:
            raise KeyError(f"配置尚未注册：{spec.name}") from error
        return cast("T", value)

    def with_value[T](self, spec: ConfigSpec[T], value: T) -> AuroraConfig:
        values = dict(self._values)
        stored_spec = cast("ConfigSpec[object]", spec)
        if stored_spec not in values:
            raise KeyError(f"不能替换尚未注册的配置：{spec.name}")
        values[stored_spec] = value
        return AuroraConfig(values, self._sources, self._project_root)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self._values)

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


def assemble_config(project_root: Path, specs: Iterable[ConfigSpec[Any]]) -> AuroraConfig:
    """按声明式规格读取全部 TOML 并生成只读配置对象。"""
    values: dict[ConfigSpec[object], object] = {}
    sources: list[ConfigSource] = []
    names: set[str] = set()
    paths: set[str] = set()
    for spec in specs:
        if spec.name in names:
            raise ValueError(f"配置重复注册：{spec.name}")
        if spec.path in paths:
            raise ValueError(f"配置文件重复注册：{spec.path}")
        names.add(spec.name)
        paths.add(spec.path)
        sources.append(ConfigSource(spec.name, spec.path))
        stored = cast("ConfigSpec[object]", spec)
        values[stored] = spec.load(project_root)
    return AuroraConfig(values, tuple(sources), project_root)
