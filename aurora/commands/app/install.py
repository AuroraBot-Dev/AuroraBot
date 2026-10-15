"""校验安装来源并生成本地或远程 App 的登记计划。"""

from __future__ import annotations

import json
import os
import string
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlsplit

from aurora.commands.app.clone import (
    Staging,
    check_clone_url,
    check_repository_name,
    github_https_path,
    normalize_repository_input,
)
from aurora.commands.app.manifest import MANIFEST_NAME
from aurora.commands.app.models import (
    CloneError,
    InstallPlan,
    LaunchCandidate,
    PackageError,
    PlanError,
    Repository,
    RunnerPlan,
    is_secret_name,
    validate_package,
)
from aurora.utils.toml import check_https_url
from src.mcp.config import AppConfig, McpEventMode, McpTransport

if TYPE_CHECKING:
    from collections.abc import Sequence

    from aurora.commands.app.store import AppStore

# 安装根目录，与 config.example/apps.toml 里既有 App 的 working_dir 同一层。
APPS_DIRECTORY = ("extensions", "apps")
# 本模块产出的计划一律是本地 stdio 进程：它要么是 clone 下来的源码，要么交给
# 包管理器去取。远程端点走 ConnectPlan，那条路径不经过这里。
DEFAULT_TRANSPORT: McpTransport = "stdio"
DEFAULT_EVENT_MODE: McpEventMode = "disabled"
# AppConfig 把这两个字段定义成必填，没有模块级默认常量；这里取的是项目惯例值，
# 与 config.example/apps.toml 的 timeout_seconds = 60、event_mode = "disabled" 一致。
DEFAULT_TIMEOUT_SECONDS = 60.0
# 包管理器型安装（--npx / --uvx）的 working_dir：它不克隆任何仓库，进程的 cwd
# 就是项目根 —— 安装根那条路径对它没有意义，而 stdio 的注册表条目必须声明一个
# 项目内相对目录。
PACKAGE_RUNNER_WORKING_DIR = "."
_CONTROL_CHARACTER_LIMIT = 0x20

_COMMAND_EVIDENCE = "explicit --command"
_MANIFEST_EVIDENCE = f"{MANIFEST_NAME} [server].command"
_DERIVED_ROOT = "github"
_FALLBACK_SEGMENT = "app"
_FALLBACK_PREFIX = "app-"
_LOWER_ASCII = frozenset(string.ascii_lowercase)
_ALLOWED_SEGMENT_CHARS = _LOWER_ASCII | frozenset(string.digits) | {"_", "-"}
# 认得出可执行名就归类，认不出就取可执行名本身——不发明一个 "unknown" 兜底值。
_RUNTIME_BY_EXECUTABLE = {
    "uv": "python-uv",
    "uvx": "python-uv",
    "node": "node",
    "npm": "node",
    "npx": "node",
    "pnpm": "node",
    "yarn": "node",
}
_PACKAGE_HINT = "--package 必须是 github.owner.repo 那样的小写点分包名"
# 包管理器型安装的 package 前缀：它们没有仓库身份，用跑它的那个命令作根段。
RUNNER_ROOTS = {"npx": "npx", "uvx": "uvx"}
# 每个包管理器在包名之前需要的固定参数。``npx`` 的 ``-y`` 不是可选项：没有它时
# npx 会在首次运行前停下来等一个确认，而 ``aurora start`` 是非交互的 —— 缺了它
# 就变成一次静默挂起，用户看到的是「App 起不来」而不是「它在等你按 y」。
RUNNER_ARGUMENTS = {"npx": ("-y",), "uvx": ()}
# 包管理器型安装的包标识：一个 npm / PyPI 包名，允许 @scope/name、pkg[extra]、
# pkg==1.0 这些写法，但不允许选项、空白与路径。
_MAX_SPECIFIER_LENGTH = 200
_URL_CREDENTIAL_HINT = "URL 里不放凭据：需要认证请用 --auth-env 指定一个环境变量名"
# query 参数名里几个太短、做子串匹配会误伤变量名的凭据名。完整判据见 _credential_name。
_URL_CREDENTIAL_NAMES = frozenset({"key", "apikey", "sig", "signature", "credential", "code"})


def check_requested_name(value: str) -> str:
    """把用户输入转换为 ``owner/repo``，用于查询 GitHub 仓库。"""
    try:
        return check_repository_name(normalize_repository_input(value))
    except CloneError as error:
        raise PlanError(str(error)) from error


def check_admission(repository: Repository) -> str:
    """校验 API 返回的仓库状态、名称和克隆地址，返回仓库全名。"""
    if repository.disabled or repository.archived:
        reason = "已禁用" if repository.disabled else "已归档"
        raise PlanError(f"仓库 {repository.full_name} {reason}，无法安装")
    try:
        full_name = check_repository_name(repository.full_name)
        # 仓库名称和克隆 URL 必须指向同一目标。
        check_clone_url(repository.clone_url, full_name)
    except CloneError as error:
        raise PlanError(str(error)) from error
    return full_name


def normalize_segment(value: str) -> str:
    """package ID 的一段：小写化、非法字符换成 ``-``、折叠连字符，并保证它以字母
    开头 —— 整段都没剩下字符时落成 ``app``，以数字或 ``-`` 开头的补 ``app-`` 前缀。

    逐段调用而不是先拼后处理：``acme/2fast`` 的两段各自得出 ``acme`` 与
    ``app-2fast``，先拼成 ``acme.2fast`` 就过不了点分包名的校验。
    """
    replaced = "".join(character if character in _ALLOWED_SEGMENT_CHARS else "-" for character in value.lower())
    collapsed = "-".join(part for part in replaced.split("-") if part)
    if not collapsed:
        return _FALLBACK_SEGMENT
    # 首字符不是 a-z 时补前缀。逐段判断是必须的：acme/2fast 的 repo 段加了前缀、
    # owner 段没加，否则 github.acme.2fast 通不过 check_package_name 的点分规则。
    return collapsed if collapsed[0] in _LOWER_ASCII else f"{_FALLBACK_PREFIX}{collapsed}"


def derive_package(full_name: str) -> str:
    """默认 package 是 ``github.<owner>.<repo>``，两段各自规范化。"""
    owner, _, name = full_name.partition("/")
    return f"{_DERIVED_ROOT}.{normalize_segment(owner)}.{normalize_segment(name)}"


def runner_package(executable: str, specifier: str) -> str:
    """包管理器型安装的默认 package：``<runner>.<包名各段>``。

    取包名本身而不是当前目录名：这类 App 没有仓库身份，包名才是它的长期 identity。
    前导 ``@`` 是 npm 的 scope 记号，不是名字的一部分，去掉后再逐段规范化。
    """
    segments = [normalize_segment(part) for part in specifier.lstrip("@").split("/") if part.strip()]
    root = RUNNER_ROOTS[executable]
    # 单段包名（uvx 很常见）补上包名自己那一层，凑够点分规则要求的至少两段。
    return ".".join([root, *segments]) if len(segments) > 1 else f"{root}.{_FALLBACK_SEGMENT}.{segments[0]}"


def remote_package(url: str) -> str:
    """从端点的主机、端口与路径生成稳定的默认 package ID。"""
    parts = urlsplit(check_connect_url(url))
    host = [normalize_segment(part) for part in (parts.hostname or "").split(".") if part]
    path = [normalize_segment(part) for part in parts.path.split("/") if part]
    try:
        port = [f"port-{parts.port}"] if parts.port is not None else []
    except ValueError as error:
        raise PlanError(f"远程 MCP URL 的端口无效：{url}") from error
    return ".".join(["remote", *host, *port, *path])


def check_runner_specifier(value: str, *, executable: str) -> str:
    """校验 ``--npx`` / ``--uvx`` 收到的包标识。

    只保证它是一件能安全放进 argv 的东西：不以 ``-`` 开头（那会被包管理器当成
    自己的选项），不含空白与控制字符，也不是路径。版本范围、extra 这些交给包
    管理器自己判断 —— Aurora 不该比 npm 更懂 npm 的包名。
    """
    specifier = value.strip()
    if not specifier:
        raise PlanError(f"--{executable} 需要包名")
    if specifier != value:
        raise PlanError(f"--{executable} 的包名不得含首尾空白：{value}")
    if specifier.startswith("-"):
        raise PlanError(f"--{executable} 的包名不得以 - 开头（那会被当成 {executable} 自己的选项）：{value}")
    if len(specifier) > _MAX_SPECIFIER_LENGTH:
        raise PlanError(f"--{executable} 的包名超过 {_MAX_SPECIFIER_LENGTH} 个字符")
    if any(character.isspace() or character in "\x00\\" for character in specifier):
        raise PlanError(f"--{executable} 的包名不得含空白、反斜杠或空字符：{value}")
    if specifier.startswith("/") or ".." in specifier:
        raise PlanError(f"--{executable} 的包名必须是包名而不是路径：{value}")
    return specifier


def check_runner_argument(value: str, *, executable: str) -> str:
    """校验一条 ``--arg``；它是 Server 自己的参数，只保证能安全放进 argv。

    与包名不同，这里不禁止前导 ``-``：``--arg --debug`` 是完全正常的用法 ——
    参数排在包名之后，包管理器会把它们交给 Server 而不是自己解析。空串与控制
    字符仍然拒绝，前者会让 Server 收到一个无意义的空参数，后者无法作为一条
    argv 传递。含空格的路径是合法值：它本来就是**一个** argv 元素，不需要转义，
    也永远不会被拼回命令行字符串。
    """
    if not value:
        raise PlanError(f"--{executable} 的 --arg 不能是空字符串")
    if any(ord(character) < _CONTROL_CHARACTER_LIMIT for character in value):
        raise PlanError(f"--{executable} 的 --arg 不得含控制字符：{value!r}")
    return value


def runner_command(executable: str, specifier: str, arguments: Sequence[str] = ()) -> tuple[str, ...]:
    """包管理器型安装的启动命令：``npx -y <pkg> [args...]`` / ``uvx <pkg> [args...]``。

    ``arguments`` 是 Server 自己的参数（例如 Filesystem Server 要的允许目录），
    排在包名之后、原样保留为独立的 argv 元素。
    """
    try:
        runner_arguments = RUNNER_ARGUMENTS[executable]
    except KeyError as error:
        raise PlanError(f"未知的包管理器 {executable}；只支持 {'、'.join(sorted(RUNNER_ROOTS))}") from error
    return (executable, *runner_arguments, specifier, *arguments)


def runner_plan(
    *,
    executable: str,
    specifier: str,
    package: str,
    arguments: Sequence[str] = (),
    enabled: bool = False,
    event_mode: McpEventMode = DEFAULT_EVENT_MODE,
) -> RunnerPlan:
    """包管理器型安装的注册计划；不做任何检测、clone 或注册表访问。

    与源码安装计划一样，它要么直接可用，要么在这一步就失败。
    """
    command = runner_command(executable, specifier, arguments)
    check_app_config(package, PACKAGE_RUNNER_WORKING_DIR, command, event_mode=event_mode)
    return RunnerPlan(
        package=package,
        command=command,
        runtime=runtime_of(command),
        working_dir=PACKAGE_RUNNER_WORKING_DIR,
        enabled=enabled,
        event_mode=event_mode,
    )


def check_user_package(value: str) -> str:
    """校验显式给出的 ``--package``；规则与运行时 AppConfig 同一条。"""
    try:
        return validate_package(value)
    except PackageError as error:
        raise PlanError(f"{_PACKAGE_HINT}：{value}") from error


def check_package_collision(store: AppStore, package: str) -> None:
    """注册表里已有同名 package 就拒绝，不自动加 -2、-3。

    package 是长期 identity，是 AppConfig 里被 aurora start 使用、被用户写进
    文档的那个名字，自动改名会让「我装的是哪个」变得不可回答。
    """
    if not store.apps_path.is_file():
        return
    if any(item.package == package for item in store.list_apps().apps):
        raise PlanError(f"注册表中已存在 package：{package}，请用 --package 指定其他 ID")


def parse_command(value: str) -> tuple[str, ...]:
    """把 ``--command`` 的 JSON 字符串数组解析成 argv 元组，永不 join 回字符串。"""
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise PlanError(f"--command 必须是 JSON 字符串数组：{error.msg}") from error
    if not isinstance(parsed, list) or not parsed:
        raise PlanError("--command 必须是长度至少 1 的 JSON 字符串数组")
    if any(not isinstance(item, str) for item in parsed):
        raise PlanError("--command 的每一项都必须是字符串")
    command = tuple(parsed)
    if not command[0].strip():
        raise PlanError("--command 的第一项不能为空")
    return command


def runtime_of(command: Sequence[str]) -> str:
    """按可执行名归类运行时；认不出来就取可执行名本身。"""
    executable = PurePosixPath(command[0].strip()).name.lower()
    return _RUNTIME_BY_EXECUTABLE.get(executable, executable or command[0])


def user_candidate(command: tuple[str, ...]) -> LaunchCandidate:
    """用户用 ``--command`` 提供入口；无需读取仓库清单。"""
    return LaunchCandidate(
        command=command,
        runtime=runtime_of(command),
        evidence=_COMMAND_EVIDENCE,
    )


def manifest_candidate(command: tuple[str, ...]) -> LaunchCandidate:
    """仓库 ``aurora-app.toml`` 声明的唯一启动命令。"""
    return LaunchCandidate(
        command=command,
        runtime=runtime_of(command),
        evidence=_MANIFEST_EVIDENCE,
    )


def install_path(full_name: str) -> str:
    """安装根目录 ``extensions/apps/<owner>/<repo>``，正好两级，与 package 无关。"""
    owner, _, name = full_name.partition("/")
    return str(PurePosixPath(*APPS_DIRECTORY, owner, name))


def subdir_parts(repository_subdir: str) -> tuple[str, ...]:
    """把 repository_subdir 拆成路径段；``.`` 拆成空元组。"""
    if repository_subdir == ".":
        return ()
    return tuple(PurePosixPath(repository_subdir).parts)


def derive_working_dir(path: str, repository_subdir: str) -> str:
    """``working_dir = install_path / repository_subdir``。"""
    return str(PurePosixPath(path, *subdir_parts(repository_subdir)))


def check_final_path(project_root: Path, path: str) -> None:
    """生成计划之前的 preflight：目标目录已存在就失败。

    提交前必须重新查一次 —— 从计划生成到用户确认执行之间隔着一次回车，
    这中间任何东西都可能出现。
    """
    if os.path.lexists(project_path(project_root, path)):
        raise PlanError(f"安装目录已存在：{path}")


def install_root(project_root: Path) -> Path:
    """``extensions/apps/`` 的绝对路径，并保证它存在。

    路径上任何一层是链接都拒绝：install_path 与 working_dir 都会写进配置，经过
    链接的「项目内相对路径」会落到项目外。stage 直接创建在这一层下面。
    """
    current = project_root
    for part in APPS_DIRECTORY:
        current = current / part
        if os.path.lexists(current) and (current.is_symlink() or current.is_junction()):
            raise PlanError(f"安装目录不得经过符号链接或联接：{current}")
    try:
        current.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise PlanError(f"无法创建安装目录 {current}：{error}") from error
    if not current.resolve().is_relative_to(project_root):
        raise PlanError(f"安装目录越出项目根目录：{current}")
    return current


@dataclass(frozen=True, slots=True)
class PreparedInstall:
    """源码安装计划及其临时克隆目录。"""

    plan: InstallPlan
    staging: Staging


def build_install_plan(
    *,
    repository: str,
    ref: str,
    commit: str,
    candidate: LaunchCandidate,
    package: str,
    path: str,
    enabled: bool = False,
    event_mode: McpEventMode = DEFAULT_EVENT_MODE,
) -> InstallPlan:
    """组装并静态校验源码安装计划。"""
    working_dir = derive_working_dir(path, candidate.repository_subdir)
    check_app_config(package, working_dir, candidate.command, event_mode=event_mode)
    return InstallPlan(
        repository=repository,
        ref=ref,
        commit=commit,
        package=package,
        install_path=path,
        repository_subdir=candidate.repository_subdir,
        working_dir=working_dir,
        transport=DEFAULT_TRANSPORT,
        command=candidate.command,
        runtime=candidate.runtime,
        evidence=candidate.evidence,
        enabled=enabled,
        event_mode=event_mode,
    )


def check_connect_url(url: str) -> str:
    """远程 MCP endpoint 的准入：HTTPS、不带凭据、也不在 query 里塞 token。

    比 ``AppConfig`` 的 ``check_https_url`` 多一条 query 判断。URL 会进注册表、
    会被日志和终端回显携带，所以「token 只在环境变量里」这条规则必须在这里也
    成立，而不只是在 ``--auth-env`` 那一侧。
    """
    try:
        check_https_url(url, "app.url")
    except ValueError as error:
        raise PlanError(f"{error}：{url}；{_URL_CREDENTIAL_HINT}") from error
    if github_https_path(url) is not None:
        raise PlanError("GitHub 仓库地址不是 MCP 端点；请提供已运行服务的 MCP Streamable HTTP URL")
    parameters = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    unsafe = sorted(name for name, _ in parameters if _credential_name(name))
    if unsafe:
        raise PlanError(f"URL 的查询参数里不得携带凭据（{'、'.join(unsafe)}）：{url}；{_URL_CREDENTIAL_HINT}")
    return url


def _credential_name(name: str) -> bool:
    """query 参数名看起来是不是在装凭据。

    比 ``is_secret_name`` 多几个短名：``?key=`` 与 ``?sig=`` 这类在 API 里就是
    凭据本身，而它们太短，做子串匹配会在变量名上误伤。
    """
    return is_secret_name(name) or name.lower() in _URL_CREDENTIAL_NAMES


def check_app_config(
    package: str,
    working_dir: str,
    command: tuple[str, ...],
    *,
    event_mode: McpEventMode = DEFAULT_EVENT_MODE,
) -> None:
    """用运行时 AppConfig 逐字段构造一遍，纯静态校验。

    不启动 Server、不连接 MCP、不做握手。AppConfig 的 ``__post_init__`` 已经包含
    package 规范、transport 枚举、stdio 与 url 的互斥、working_dir 的相对性与
    非符号链接等判断，直接复用比在这里重写一套更可靠 —— 这里产出的字段与
    ``aurora start`` 读到的必须是同一套规则。
    """
    try:
        AppConfig(
            package=package,
            enabled=False,
            transport=DEFAULT_TRANSPORT,
            event_mode=event_mode,
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
            working_dir=working_dir,
            command=command,
            env=(),
        )
    except ValueError as error:
        raise PlanError(f"生成的安装配置不合法：{error}") from error


def check_remote_config(
    package: str,
    url: str,
    auth_env: str | None,
    *,
    event_mode: McpEventMode = DEFAULT_EVENT_MODE,
) -> None:
    """远程条目的静态校验；与 ``check_app_config`` 对称，同样复用 AppConfig。

    streamable_http 的字段白名单与 stdio 不同（``url`` / ``auth_env`` 取代
    ``working_dir`` / ``command`` / ``env``），所以不能共用一次构造。
    """
    check_connect_url(url)
    try:
        AppConfig(
            package=package,
            enabled=False,
            transport="streamable_http",
            event_mode=event_mode,
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
            url=url,
            auth_env=auth_env,
        )
    except ValueError as error:
        raise PlanError(f"生成的连接配置不合法：{error}") from error


def project_path(project_root: Path, path: str) -> Path:
    """把一条项目内相对路径（TOML 里的正斜杠形式）拼成绝对路径。"""
    return project_root.joinpath(*PurePosixPath(path).parts)


__all__ = [
    "APPS_DIRECTORY",
    "DEFAULT_EVENT_MODE",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_TRANSPORT",
    "PACKAGE_RUNNER_WORKING_DIR",
    "RUNNER_ARGUMENTS",
    "RUNNER_ROOTS",
    "PreparedInstall",
    "build_install_plan",
    "check_admission",
    "check_app_config",
    "check_connect_url",
    "check_final_path",
    "check_package_collision",
    "check_remote_config",
    "check_requested_name",
    "check_runner_argument",
    "check_runner_specifier",
    "check_user_package",
    "derive_package",
    "derive_working_dir",
    "install_path",
    "install_root",
    "manifest_candidate",
    "normalize_segment",
    "parse_command",
    "project_path",
    "remote_package",
    "runner_command",
    "runner_package",
    "runner_plan",
    "runtime_of",
    "subdir_parts",
    "user_candidate",
]
