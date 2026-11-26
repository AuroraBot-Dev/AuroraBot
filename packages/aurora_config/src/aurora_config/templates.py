"""配置模板定位与宿主引导共用的 TOML 文件操作。"""

import tomllib
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path, PurePosixPath

from aurora_core.ids import validate_namespace


@dataclass(frozen=True)
class ConfigTemplate:
    """包资源为 config.toml 或 config.tomls/ 下的 TOML 相对路径。"""

    package: str
    resource: str = "config.toml"
    owner: str | None = None

    def __post_init__(self) -> None:
        path = PurePosixPath(self.resource)
        if (
            not self.package
            or "\\" in self.resource
            or path.is_absolute()
            or any(part in ("", ".", "..") or ":" in part for part in self.resource.split("/"))
            or path.suffix != ".toml"
            or not (self.resource == "config.toml" or (len(path.parts) > 1 and path.parts[0] == "config.tomls"))
        ):
            raise ValueError("配置模板必须指向包内 config.toml 或 config.tomls/ 下的 TOML 文件")
        if self.owner is not None:
            validate_namespace(self.owner)

    def source(self):
        package = files(self.package)
        if package.joinpath("config.toml").is_file() and package.joinpath("config.tomls").is_dir():
            raise ValueError(f"配置模板不能同时提供 config.toml 与 config.tomls：{self.package}")
        source = package.joinpath(*PurePosixPath(self.resource).parts)
        if not source.is_file():
            raise ValueError(f"配置模板不存在：{self.package}/{self.resource}")
        return source


def checked_path(path: Path) -> Path:
    """拒绝配置文件及父目录中的路径重定向。"""
    path = path.absolute()
    if path.resolve() != path:
        raise ValueError(f"配置路径存在重定向：{path}")
    return path


def read_toml(path: Path) -> dict:
    checked_path(path)
    try:
        return tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except (tomllib.TOMLDecodeError, UnicodeError):
        raise ValueError(f"TOML 配置无法解析：{path}") from None


def copy_missing(path: Path, content: bytes) -> None:
    checked_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(content)
    except FileExistsError:
        pass
