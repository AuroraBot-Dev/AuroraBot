"""``config/apps.toml`` 的唯一读写边界：注册表读取、原子写与路径安全。"""

from __future__ import annotations

import os
import stat
import tempfile
import tomllib
from contextlib import suppress
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, cast

import tomlkit
from tomlkit.exceptions import ParseError
from tomlkit.items import AoT, Array, Table

from aurora.commands.app.models import (
    AppList,
    AppListItem,
    AppNotFoundError,
    AppState,
    ConfigError,
    PathError,
    RawApp,
    RegistryError,
    RegistryWriteError,
    registry_package,
)
from aurora.utils.toml import TomlTable, boolean, load_toml, optional_text, positive_number, strings, table_array, text
from aurorabot.mcp.config import AppConfig, McpEventMode, McpTransport
from aurorabot.utils.validation import check_relative_directory, check_unique_items

if TYPE_CHECKING:
    from tomlkit.toml_document import TOMLDocument

APPS_RELATIVE_PATH = "config/apps.toml"


class AppStore:
    """``config/apps.toml`` 的读取、修改与路径安全边界。"""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.apps_path = self.project_root / APPS_RELATIVE_PATH

    def list_apps(self) -> AppList:
        """正向读取注册表并核对每个条目自身的 working_dir；不反向扫描磁盘。"""
        raw_apps = _raw_apps(self._read_document())
        packages = _packages(raw_apps)
        items = tuple(self._item(package, raw) for package, raw in zip(packages, raw_apps, strict=True))
        return AppList(items)

    def require_registry(self) -> None:
        """注册表不存在即 ConfigError；要写它的用例在动手之前先调这一条。

        读取入口（``_read_document`` / ``_editable_document``）也各自调它一次，
        所以「文件不存在」在任何路径上都是同一句话。这里公开出来只是为了让
        install 能在 clone 之前就问 —— 否则用户会先等完一整次 clone 才被告知
        「先去 aurora setup」，而这句话在动手之前就能说。
        """
        if not self.apps_path.is_file():
            raise _missing_registry(self.apps_path)

    def set_enabled(self, package: str, enabled: bool) -> bool:
        """原子修改一个已有条目的 enabled；返回是否实际改动了文件。"""
        document = self._editable_document()
        matches = [entry for entry in _apps_array(document) if entry.get("package") == package]
        if not matches:
            raise AppNotFoundError(f"注册表中不存在 package：{package}")
        if len(matches) > 1:
            raise RegistryError(f"{APPS_RELATIVE_PATH} 中 package 重复：{package}")
        entry = matches[0]
        current = entry.get("enabled")
        if isinstance(current, bool) and current is enabled:
            return False
        entry["enabled"] = enabled
        _atomic_write(self.apps_path, tomlkit.dumps(document))
        return True

    def raw_app(self, package: str) -> RawApp | None:
        """按 package 取一条注册表条目的原始声明；不存在时返回 None。

        列表投影不能当这个用途：无效条目的 working_dir 会被压成展示占位符
        ``"-"``，remove 需要区分「用户写的字符串」与「那个占位符」。
        """
        raw_apps = _raw_apps(self._read_document())
        packages = _packages(raw_apps)
        for name, raw in zip(packages, raw_apps, strict=True):
            if name == package:
                return RawApp(name, _declared_optional(raw, "working_dir"), _app_config(name, raw))
        return None

    def add_app(self, entry: AppConfig) -> None:
        """追加一条条目并原子写注册表。

        接收 ``AppConfig`` 而不是计划：store 只认识注册表条目的形状，不知道
        GitHub、包管理器与远程端点。写出的字段恰好是 runtime 解析器为该传输开的
        那一份白名单键（见 ``app_table``）—— 多一个 key 会让 ``aurora start``
        拒绝整个文件。
        """
        document = self._editable_document()
        _apps_array(document).append(app_table(entry))
        _atomic_write(self.apps_path, tomlkit.dumps(document))

    def remove_app(self, package: str) -> None:
        """删除一条条目并原子写注册表；package 不存在即 AppNotFoundError。"""
        document = self._editable_document()
        apps = _apps_array(document)
        matches = [index for index, entry in enumerate(apps) if entry.get("package") == package]
        if not matches:
            raise AppNotFoundError(f"注册表中不存在 package：{package}")
        if len(matches) > 1:
            raise RegistryError(f"{APPS_RELATIVE_PATH} 中 package 重复：{package}")
        del apps[matches[0]]
        if len(apps) == 0:
            _keep_empty_apps_array(document)
        _atomic_write(self.apps_path, tomlkit.dumps(document))

    def validate_registered_working_dir(self, working_dir: str) -> Path:
        """校验已注册 App 的 working_dir，返回项目内的绝对路径。

        事务目录（暂存、回收）不适用这条规则，它们走 ``check_project_directory``
        加自己的形状判断。
        """
        try:
            check_relative_directory(working_dir, "app.working_dir")
        except ValueError as error:
            raise PathError(f"working_dir 必须是项目内相对目录：{working_dir}") from error
        normalized = PurePosixPath(working_dir.replace("\\", "/"))
        return check_project_directory(self.project_root, self.project_root.joinpath(*normalized.parts), "working_dir")

    def _read_document(self) -> TomlTable:
        self.require_registry()
        try:
            return load_toml(self.apps_path)
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise ConfigError(f"{APPS_RELATIVE_PATH} 无法解析：{error}") from error

    def _item(self, package: str, raw: TomlTable) -> AppListItem:
        """把一个条目投影成列表项；条目字段问题只影响它自己，不影响整次读取。

        两种传输的「自身可用」不是同一件事：本地条目要核对磁盘上的 working_dir，
        远程条目没有本地文件可查。远程因此是 ``configured`` 而不是 ``ready`` ——
        它说的是「这一条读得通、可以交给 aurora start」，端点是否在线由
        运行期会重新连接；列表不探测端点状态。
        """
        transport = _declared_text(raw, "transport")
        config = _app_config(package, raw)
        if config is None:
            return AppListItem(package, False, transport, "invalid", _declared_text(raw, "working_dir"))
        if config.transport == "stdio":
            state = self._stdio_state(config.working_dir or "")
            return AppListItem(package, config.enabled, "stdio", state, config.working_dir)
        return AppListItem(package, config.enabled, config.transport, "configured", None)

    def _stdio_state(self, working_dir: str) -> AppState:
        try:
            directory = self.validate_registered_working_dir(working_dir)
        except PathError:
            return "invalid"
        return "ready" if directory.is_dir() else "missing"

    def _editable_document(self) -> TOMLDocument:
        self.require_registry()
        try:
            return tomlkit.parse(self.apps_path.read_text(encoding="utf-8"))
        except (OSError, ParseError) as error:
            raise ConfigError(f"{APPS_RELATIVE_PATH} 无法解析：{error}") from error


def _missing_registry(path: Path) -> ConfigError:
    """config/ 是 git 忽略的个人配置，缺失时指向生成它的命令而不是模板。"""
    return ConfigError(
        f"未找到 {APPS_RELATIVE_PATH}：{path}；先运行 aurora setup 生成个人配置，或从 config.example/apps.toml 复制。"
    )


def _raw_apps(document: TomlTable) -> tuple[TomlTable, ...]:
    try:
        return table_array(document, "app")
    except ValueError as error:
        raise RegistryError(f"{APPS_RELATIVE_PATH} 无效：{error}") from error


def _packages(raw_apps: tuple[TomlTable, ...]) -> tuple[str, ...]:
    """读取全部 package 并检查唯一性；重复时无法确定该操作哪一个条目。"""
    packages = tuple(registry_package(raw.get("package"), APPS_RELATIVE_PATH) for raw in raw_apps)
    try:
        check_unique_items(packages, "app.package")
    except ValueError as error:
        repeated = sorted({package for package in packages if packages.count(package) > 1})
        raise RegistryError(f"{APPS_RELATIVE_PATH} 中 package 重复：{'、'.join(repeated)}") from error
    return packages


def _apps_array(document: TOMLDocument) -> AoT:
    """取出可编辑的 ``[[app]]`` 表数组；缺失或 ``app = []`` 都补一个空的。

    空数组没有 append，而删除条目与新增条目必须拿到同一个容器，所以这里就地
    把它换成表数组。只有真正要改文件的入口会调用它。
    """
    entries = document.get("app")
    if isinstance(entries, AoT):
        return entries
    if entries is None or (isinstance(entries, Array) and len(entries) == 0):
        if entries is not None:
            del document["app"]
        empty = tomlkit.aot()
        document["app"] = empty
        return empty
    raise RegistryError(f"{APPS_RELATIVE_PATH} 的 app 必须是表数组")


def _keep_empty_apps_array(document: TOMLDocument) -> None:
    """把空掉的表数组换成 ``app = []``。

    删掉最后一条之后 tomlkit 会把整个键渲染掉，文件里就只剩一个空文档 ——
    而读取端要求 ``app`` 存在且是表数组，于是「移除最后一个 App」会把注册表
    变成一份读不了的文件。空注册表的写法就是 ``app = []``，这里沿用同一种表示，
    不把空数组留成一个缺失的键。
    """
    del document["app"]
    document["app"] = tomlkit.array()


def render_entry(entry: AppConfig) -> str:
    """把一条条目渲染成 ``[[app]]`` 文本块，用于安装确认时展示。

    展示给用户的这段文本与最终写进文件的那一段出自同一个 ``app_table``：计划里
    写 enabled = true，注册表就是 true，不存在两处各自渲染、各自漂移的可能。
    """
    document = tomlkit.document()
    _apps_array(document).append(app_table(entry))
    return tomlkit.dumps(document).strip()


def app_table(entry: AppConfig) -> Table:
    """把一条配置写成 TOML 表；字段与顺序对齐 config.example/apps.toml。

    两种传输的键集不同，因为运行时解析器对它们各开了一份封闭白名单：stdio 条目
    多一个键就会被 ``aurora start`` 拒绝整个文件，streamable_http 条目多一个
    ``working_dir`` 同样如此。所以这里按 transport 分支，而不是写一份合并的。
    远程条目未声明认证变量时省略 auth_env，避免写入不能被配置解析器接受的空值。
    """
    rendered = tomlkit.table()
    rendered["package"] = entry.package
    rendered["enabled"] = entry.enabled
    rendered["transport"] = entry.transport
    if entry.transport == "stdio":
        rendered["working_dir"] = entry.working_dir
        rendered["command"] = list(entry.command)
        rendered["env"] = list(entry.env)
    else:
        rendered["url"] = entry.url
        if entry.auth_env is not None:
            rendered["auth_env"] = entry.auth_env
    rendered["timeout_seconds"] = entry.timeout_seconds
    rendered["event_mode"] = entry.event_mode
    return rendered


def _declared_text(raw: TomlTable, key: str) -> str:
    """按注册表原样展示字段；缺失或非文本时用占位符。"""
    value = raw.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else "-"


def _declared_optional(raw: TomlTable, key: str) -> str | None:
    """注册表里的原始文本；缺失、空白或类型不对时返回 None。

    与 ``_declared_text`` 只差兜底值：那个是给表格看的 ``"-"``，这个是给判断
    看的「没有」。占位符必须能被识别出来，否则 remove 会把 ``"-"`` 当路径。
    """
    value = raw.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def check_project_directory(project_root: Path, directory: Path, label: str) -> Path:
    """确认一个项目内目录不经链接、不越界，返回它。

    ``label`` 只进错误信息：调用方说得出自己在处理什么（working_dir、受管安装
    根），用户才知道该去改哪一行配置。路径安全是绝对的，不由任何参数开启 ——
    install 与 remove 走的是同一条规则。
    """
    for component in _components(project_root, directory):
        if os.path.lexists(component) and (component.is_symlink() or component.is_junction()):
            raise PathError(f"{label} 不得经过符号链接或联接：{component}")
    if not directory.resolve().is_relative_to(project_root):
        raise PathError(f"{label} 越出项目根目录：{directory}")
    return directory


def _components(root: Path, path: Path) -> tuple[Path, ...]:
    """从项目根开始逐层枚举路径的每一级，用于检查链接与联接。"""
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise PathError(f"路径不在项目根目录内：{path}") from error
    current = root
    components: list[Path] = []
    for part in relative.parts:
        current = current / part
        components.append(current)
    return tuple(components)


def _app_config(package: str, raw: TomlTable) -> AppConfig | None:
    """用运行时 AppConfig 校验单个条目；字段不合规时该条目为 invalid。"""
    try:
        return _build_app_config(package, raw)
    except (TypeError, ValueError):
        return None


def _build_app_config(package: str, raw: TomlTable) -> AppConfig:
    transport = cast("McpTransport", text(raw, "transport"))
    common = {
        "package": package,
        "enabled": boolean(raw, "enabled"),
        "transport": transport,
        "event_mode": cast("McpEventMode", optional_text(raw, "event_mode") or "disabled"),
        "timeout_seconds": positive_number(raw, "timeout_seconds"),
    }
    if transport == "stdio":
        return AppConfig(
            **common,
            working_dir=text(raw, "working_dir"),
            command=strings(raw, "command"),
            env=strings(raw, "env"),
        )
    return AppConfig(**common, url=text(raw, "url"), auth_env=optional_text(raw, "auth_env"))


def _atomic_write(path: Path, content: str) -> None:
    """同目录临时文件 + fsync + 原子替换；任一步失败都保留原文件。"""
    temporary = _write_temporary(path, content)
    try:
        _replace(temporary, path)
    except OSError as error:
        raise RegistryWriteError(f"无法写入 {path.name}：{error}{_discard(temporary)}") from error
    _discard(temporary)


def _write_temporary(path: Path, content: str) -> Path:
    """在目标同目录写入并落盘临时文件；跨文件系统的替换没有原子语义。"""
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        _copy_mode(path, temporary)
    except OSError as error:
        raise RegistryWriteError(f"无法写入 {path.name}：{error}{_discard(temporary)}") from error
    return temporary


def _replace(source: Path, target: Path) -> None:
    """原子替换；独立成函数以便测试注入失败路径。"""
    source.replace(target)


def _copy_mode(source: Path, target: Path) -> None:
    """让临时文件继承原文件权限，避免替换后文件权限发生变化。"""
    try:
        mode = stat.S_IMODE(source.stat().st_mode)
    except OSError:
        return
    with suppress(OSError):
        target.chmod(mode)


def _discard(path: Path) -> str:
    """删除临时文件；失败时返回残留路径提示，不改变主错误。"""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return f"；残留临时文件 {path}"
    return ""


__all__ = [
    "APPS_RELATIVE_PATH",
    "AppStore",
    "app_table",
    "check_project_directory",
    "render_entry",
]
