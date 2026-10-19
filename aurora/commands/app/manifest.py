"""解析仓库的 ``aurora-app.toml`` 启动清单，内容限制为 64 KiB。"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass

from aurora.commands.app.models import ManifestError
from src.utils.validation import check_relative_directory

MANIFEST_NAME = "aurora-app.toml"
MANIFEST_VERSION = 1
MAX_MANIFEST_BYTES = 64 * 1024

_SERVER_FIELDS = frozenset({"command"})
_TOP_LEVEL_FIELDS = frozenset({"manifest_version", "server"})
_COMMAND_HINT = f"仓库根目录提供 {MANIFEST_NAME}，其中 [server].command 是启动这个 MCP Server 的 argv"
_ESCAPE_HINT = "如仍要安装，请用 --command 显式给出启动命令；已经在运行的远程 MCP 请直接安装它的地址"


@dataclass(frozen=True, slots=True)
class Manifest:
    """一份通过校验的 ``aurora-app.toml``。"""

    command: tuple[str, ...]


def manifest_source(full_name: str, ref: str | None) -> str:
    """错误信息里指认一份清单的出处：``owner/repo``，指定了 --ref 就写成 ``owner/repo@ref``。

    只有一个地方拼这个字符串，因为读取（Contents API）与解析（``parse_manifest``）
    是两次调用、两个模块，而它们说的必须是同一份清单。
    """
    return f"{full_name}@{ref}" if ref is not None else full_name


def parse_manifest(content: str, *, source: str) -> Manifest:
    """解析清单文本；任何不合规都是 ``ManifestError``。

    ``source`` 只进错误信息，说明这份内容是从哪里读来的（``owner/repo@ref``）。
    严格拒绝未知字段而不是忽略：清单是契约，多写一个 Aurora 不认识的键，多半是
    作者以为它生效了。
    """
    try:
        document = tomllib.loads(content)
    except tomllib.TOMLDecodeError as error:
        raise ManifestError(f"{source} 的 {MANIFEST_NAME} 无法解析：{error}") from error
    if not isinstance(document, Mapping):
        raise ManifestError(f"{source} 的 {MANIFEST_NAME} 顶层必须是表")
    _reject_unknown(document, _TOP_LEVEL_FIELDS, source, MANIFEST_NAME)
    version = document.get("manifest_version")
    if version != MANIFEST_VERSION or isinstance(version, bool):
        raise ManifestError(f"{source} 的 {MANIFEST_NAME} 必须声明 manifest_version = {MANIFEST_VERSION}")
    server = document.get("server")
    if not isinstance(server, Mapping):
        raise ManifestError(f"{source} 的 {MANIFEST_NAME} 缺少 [server] 表")
    _reject_unknown(server, _SERVER_FIELDS, source, f"{MANIFEST_NAME} 的 [server]")
    return Manifest(command=_command(server.get("command"), source))


def check_manifest_command(command: tuple[str, ...], *, source: str) -> tuple[str, ...]:
    """校验一份 argv；清单与 ``--command`` 共用这一条规则。

    参数本身不设白名单：仓库作者声明的就是他要执行的，Aurora 不做「命令看起来危不
    危险」的判断 —— 那种判断既拦不住真的恶意，又会误伤合法的启动方式。这里只保证
    它是一个能直接交给 ``exec`` 的形状。
    带路径分隔符的可执行名必须是仓库内的相对路径，避免按工作目录解析时越界。
    """
    if not command:
        raise ManifestError(f"{source} 必须是非空的字符串数组")
    if command[0].strip() != command[0] or not command[0].strip():
        raise ManifestError(f"{source} 的第一项必须是非空的可执行名，且不含首尾空白")
    if any(item.strip() != item for item in command):
        raise ManifestError(f"{source} 的每一项都不得含首尾空白")
    if "/" in command[0] or "\\" in command[0]:
        try:
            check_relative_directory(command[0], f"{source}[0]")
        except ValueError as error:
            raise ManifestError(f"{source} 的可执行名必须是仓库内的相对路径：{error}") from error
    return command


def _command(value: object, source: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ManifestError(f"{source} 的 {MANIFEST_NAME} 的 [server].command 必须是字符串数组；{_COMMAND_HINT}")
    return check_manifest_command(tuple(value), source=f"{source} 的 [server].command")


def _reject_unknown(document: Mapping[str, object], allowed: frozenset[str], source: str, label: str) -> None:
    unknown = sorted(set(document) - allowed)
    if unknown:
        raise ManifestError(f"{source} 的 {label} 含未知字段 {unknown}，只允许 {sorted(allowed)}")


def missing_manifest(source: str) -> ManifestError:
    """仓库没有清单时的统一说法；``source`` 形如 ``owner/repo@main``。"""
    return ManifestError(f"{source} 没有 {MANIFEST_NAME}，未声明怎么启动它；{_COMMAND_HINT}。{_ESCAPE_HINT}。")


def unusable_manifest(source: str, detail: str) -> ManifestError:
    """清单存在但读不到内容，或内容大到不像清单。"""
    return ManifestError(f"{source} 的 {MANIFEST_NAME} 不可用：{detail}。{_ESCAPE_HINT}。")


__all__ = [
    "MANIFEST_NAME",
    "MANIFEST_VERSION",
    "MAX_MANIFEST_BYTES",
    "Manifest",
    "check_manifest_command",
    "manifest_source",
    "missing_manifest",
    "parse_manifest",
    "unusable_manifest",
]
