"""安全地克隆 Git 仓库并管理暂存目录。

暂存目录使用隐藏的单层名称，与受管安装的 ``owner/repo`` 两级路径区分。
提交摘要接受至少七位十六进制字符，输入支持 GitHub 的 HTTPS、SSH 和 CLI 写法。
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlsplit

from aurora.commands.app.models import CloneError, CloneResult, Repository

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence

GIT_CLONE_TIMEOUT_SECONDS = 300.0
MIN_COMMIT_LENGTH = 7
STAGE_PREFIX = ".aurora-stage-"
_SCRATCH_PREFIX = ".aurora-git-"
_EMPTY_CONFIG_NAME = "empty-gitconfig"
_EMPTY_HOOKS_NAME = "empty-hooks"
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
_STDERR_TAIL = 400
_STDERR_LINES = 4
_GITHUB_HOST = "github.com"
_GIT_SUFFIX = ".git"
_GH_CLONE_PREFIX = "gh repo clone"
_SSH_USER = "git"
_ACCEPTED_FORMS = "支持 owner/repo，以及 GitHub 页面上的 HTTPS、SSH、GitHub CLI 三种写法"


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """一次捕获式子进程执行的结果。"""

    returncode: int
    stdout: str
    stderr: str


class ProcessRunner(Protocol):
    """``GitRepositoryCloner`` 依赖的最小进程边界；测试注入假实现。

    不复用 ``aurora.utils.process.run_process``：那个把输出实时打到 stdout、不
    捕获 stderr、只返回退出码，也没有这里需要的 timeout。它是给 ``aurora start``
    那种前台实时输出用的，为 clone 去扩它会同时伤害那两个场景。
    """

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        timeout: float,
        env: Mapping[str, str] | None = None,
    ) -> ProcessResult: ...


class CapturedProcessRunner:
    """执行 argv 并分开捕获两个输出流；shell 恒为 False。"""

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        timeout: float,
        env: Mapping[str, str] | None = None,
    ) -> ProcessResult:
        executable = shutil.which(command[0])
        if executable is None:
            raise CloneError(f"未找到命令 {command[0]}，请先安装并加入 PATH 后重试。")
        try:
            result = subprocess.run(
                [executable, *command[1:]],
                cwd=cwd,
                env=None if env is None else dict(env),
                capture_output=True,
                shell=False,
                check=False,
                timeout=timeout,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired as error:
            raise CloneError(f"{command[0]} 超过 {timeout:g} 秒未结束，已终止") from error
        except OSError as error:
            raise CloneError(f"无法执行 {command[0]}：{error}") from error
        return ProcessResult(result.returncode, result.stdout or "", result.stderr or "")


@dataclass(frozen=True, slots=True)
class Staging:
    """一次安装计划的事务工作目录。

    ``root`` 是仓库本体的落点，``scratch`` 放 Git 隔离用的空配置文件与空 hooks
    目录。两者都在 ``extensions/apps/`` 下、都以保留前缀命名，但都不是 registered
    App 路径，因此不适用「恰好两级」那条规则。
    """

    root: Path
    scratch: Path


@contextmanager
def staging_directory(apps_root: Path) -> Iterator[Staging]:
    """创建 staging 并保证无论成败都清理干净。

    写成上下文管理器而不是「在 plan_install 末尾调 rmtree」：失败路径有很多条
    （clone、分析、冲突、路径校验），加一条提前 return 就会漏掉清理，而漏掉的
    后果是 extensions/apps/ 下留下一个看不出用途的目录。
    """
    scratch = Path(tempfile.mkdtemp(prefix=_SCRATCH_PREFIX, dir=apps_root))
    root = apps_root / f"{STAGE_PREFIX}{uuid.uuid4().hex}"
    try:
        root.mkdir()
        yield Staging(root=root, scratch=scratch)
    finally:
        _remove(root)
        _remove(scratch)


def isolated_git_environment(base: Mapping[str, str], empty_config: Path) -> dict[str, str]:
    """保留基础系统环境，只覆盖 Git 的 global 与 system 配置。

    只关掉 redirect 不够：``url.<base>.insteadOf`` 在 Git 发起请求之前就把已经
    通过校验的 URL 换成别的主机，而它来自用户本机的 gitconfig。清空 PATH 会让
    git 自己都找不到，所以只覆盖这两个变量。
    """
    environment = dict(base)
    environment["GIT_CONFIG_GLOBAL"] = str(empty_config)
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    return environment


def check_repository_name(value: str) -> str:
    """校验 ``owner/repo`` 恰好两段且各段非空，返回原值。

    用 partition 而不是 split：它天然表达「恰好一个分隔符」，也就不用拿段数与
    字面量 2 去比。
    """
    owner, separator, name = value.partition("/")
    if not separator or not _clean_segment(owner) or not _clean_segment(name):
        raise CloneError(f"仓库全名必须是 owner/repo 两段：{value}")
    return value


def _clean_segment(part: str) -> bool:
    """一段仓库名：非空、无首尾空白、不是相对路径段、不含分隔符。"""
    return bool(part) and part == part.strip() and part not in {".", ".."} and "/" not in part


def github_https_path(url: str) -> str | None:
    """把 ``https://github.com/<owner>/<repo>[.git]`` 解析成 ``owner/repo``。

    不是这个形状就返回 None。clone 方向与 origin 归属方向共用这一条解析规则：
    前者问「准备 clone 的 URL 是不是这个仓库」，后者问「这个目录是不是从那个
    仓库来的」。ssh、git 协议、带 userinfo、带 query / fragment / 端口一律
    不在其中 —— 它们都不是 Aurora 自己会写出来的 URL。
    """
    parsed = urlsplit(url)
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname != _GITHUB_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.port is not None
    ):
        return None
    return _strip_git_suffix(parsed.path.lstrip("/")) or None


def _strip_git_suffix(path: str) -> str:
    """去掉可选的 ``.git`` 后缀。"""
    return path[: -len(_GIT_SUFFIX)] if path.endswith(_GIT_SUFFIX) else path


def normalize_repository_input(value: str) -> str:
    """将受支持的 GitHub 仓库写法转换为 ``owner/repo``。"""
    text = value.strip().rstrip("/")
    if text.lower().startswith(_GH_CLONE_PREFIX):
        text = text[len(_GH_CLONE_PREFIX) :].strip()
    if text.lower().startswith(f"{_SSH_USER}@"):
        return _github_scp_path(text)
    if "://" in text:
        return _github_url_path(text)
    host_prefix = f"{_GITHUB_HOST}/"
    if text.lower().startswith(host_prefix):
        return text[len(host_prefix) :]
    return text


def _github_scp_path(text: str) -> str:
    """解析 ``git@github.com:owner/repo[.git]``。"""
    user, at, remainder = text.partition("@")
    host, colon, path = remainder.partition(":")
    if not at or not colon or user.lower() != _SSH_USER or host.lower() != _GITHUB_HOST:
        raise CloneError(_unrecognized(text))
    return _strip_git_suffix(path.lstrip("/"))


def _github_url_path(text: str) -> str:
    """解析 HTTPS 或 SSH 仓库地址；HTTPS 与克隆地址、origin 使用同一套校验。"""
    scheme = urlsplit(text).scheme.lower()
    if scheme == "https":
        path = github_https_path(text)
    elif scheme == "ssh":
        path = _github_ssh_url_path(text)
    else:
        path = None
    if path is None:
        raise CloneError(_unrecognized(text))
    return path


def _github_ssh_url_path(text: str) -> str | None:
    """``ssh://git@github.com/owner/repo[.git]``；不是这个形状返回 None。"""
    parsed = urlsplit(text)
    if (
        parsed.hostname != _GITHUB_HOST
        or parsed.username not in (None, _SSH_USER)
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.port is not None
    ):
        return None
    return _strip_git_suffix(parsed.path.lstrip("/")) or None


def _unrecognized(value: str) -> str:
    """一句能照着改的提示：把接受的写法都摆出来。"""
    return f"无法识别的仓库写法：{value}；{_ACCEPTED_FORMS}"


def check_clone_url(clone_url: str, full_name: str) -> str:
    """校验 clone_url 确实指向这个仓库，返回原值。

    两步缺一不可：先证明「这是一个 github.com 的 HTTPS URL」，再证明「这是这个
    Repository 的 URL」。只做第一步的话，full_name 是 example/weather-mcp 而
    clone_url 指向 evil/other.git 时全部检查照样通过。
    """
    path = github_https_path(clone_url)
    if path is None:
        raise CloneError(f"clone_url 必须是 https://{_GITHUB_HOST}/<owner>/<repo>：{clone_url}")
    if path != full_name:
        raise CloneError(f"clone_url 与仓库全名不一致：{clone_url} 不是 {full_name}")
    return clone_url


def check_commit(value: str) -> str:
    """校验 ``git rev-parse`` 的输出。

    这条 hex 规则只用于校验 git 的输出，不用于判断用户的 ``--ref`` —— 两者不是
    同一个问题，叫 deadbeef 的 branch 完全合法。
    """
    commit = value.strip()
    if len(commit) < MIN_COMMIT_LENGTH or any(character not in _HEX_DIGITS for character in commit):
        raise CloneError(f"git 返回的 HEAD 不是有效的 commit：{commit[:80]}")
    return commit.lower()


class Cloner(Protocol):
    """源码安装使用的仓库克隆接口。"""

    def clone(self, repository: Repository, target: Staging, *, ref: str | None = None) -> CloneResult: ...


class GitRepositoryCloner:
    """把一个已通过校验的 Repository 浅克隆到 staging 目录。"""

    def __init__(self, runner: ProcessRunner, *, timeout: float = GIT_CLONE_TIMEOUT_SECONDS) -> None:
        self._runner = runner
        self._timeout = timeout

    def clone(self, repository: Repository, target: Staging, *, ref: str | None = None) -> CloneResult:
        """浅克隆并解析实际 HEAD；失败一律转 ``CloneError``。"""
        check_clone_url(repository.clone_url, repository.full_name)
        empty_config = _empty_file(target.scratch / _EMPTY_CONFIG_NAME)
        empty_hooks = _empty_directory(target.scratch / _EMPTY_HOOKS_NAME)
        environment = isolated_git_environment(os.environ, empty_config)
        result = self._runner.run(
            _clone_arguments(repository.clone_url, target.root, empty_hooks, ref),
            cwd=target.root.parent,
            timeout=self._timeout,
            env=environment,
        )
        if result.returncode != 0:
            raise CloneError(_clone_failure(result, ref))
        return CloneResult(
            repository=repository.full_name,
            path=target.root,
            ref=ref or repository.default_branch or "HEAD",
            commit=self._head_commit(target.root, environment),
        )

    def _head_commit(self, destination: Path, environment: Mapping[str, str]) -> str:
        """取实际 checkout 的 commit。

        不用 GitHub API 的 SHA：API 的默认分支 HEAD 与 ``--ref`` 指定的分支或标签
        可能不是同一个 commit，而真正落盘的是 clone 下来的那一份。
        """
        result = self._runner.run(
            ["git", "-C", str(destination), "rev-parse", "HEAD"],
            cwd=destination,
            timeout=self._timeout,
            env=environment,
        )
        if result.returncode != 0:
            raise CloneError(f"无法读取 clone 后的 HEAD（退出码 {result.returncode}）：{_tail(result.stderr)}")
        return check_commit(result.stdout)


def _clone_arguments(url: str, destination: Path, hooks: Path, ref: str | None) -> list[str]:
    """浅克隆的完整 argv；``--branch`` 与 ``--single-branch`` 只在指定 ref 时出现。

    ``http.followRedirects=false`` 挡住 302 换源；``core.hooksPath`` 指向一个空
    目录，隔离用户本机配置的钩子与 git template 里的钩子。``--`` 让 URL 不可能
    被当成选项。
    """
    arguments = [
        "git",
        "-c",
        "http.followRedirects=false",
        "-c",
        f"core.hooksPath={hooks}",
        "clone",
        "--depth",
        "1",
    ]
    if ref is not None:
        arguments += ["--branch", ref, "--single-branch"]
    return [*arguments, "--", url, str(destination)]


def _clone_failure(result: ProcessResult, ref: str | None) -> str:
    """把失败的 clone 说清楚；ref 像 hex 时附一句提示，但不下断言。"""
    message = f"git clone 失败（退出码 {result.returncode}）"
    tail = _tail(result.stderr)
    if tail:
        message = f"{message}：{tail}"
    if ref is not None and _looks_like_hex(ref):
        message = f"{message}；本版本不支持按 commit 安装，--ref 只接受分支或标签"
    return message


def _looks_like_hex(value: str) -> bool:
    """只用来决定要不要附那句提示，不用来判定 ref 的类型。"""
    return len(value) >= MIN_COMMIT_LENGTH and all(character in _HEX_DIGITS for character in value)


def _tail(text: str) -> str:
    """stderr 的有限长度尾巴；不把整份输出带进错误信息。"""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " ".join(lines[-_STDERR_LINES:])[:_STDERR_TAIL]


def _empty_file(path: Path) -> Path:
    """一个真实存在的空配置文件；不用 /dev/null，那个在 Windows 上是 NUL。"""
    try:
        path.write_text("", encoding="utf-8")
    except OSError as error:
        raise CloneError(f"无法创建 Git 配置隔离文件：{error}") from error
    return path


def _empty_directory(path: Path) -> Path:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise CloneError(f"无法创建空 hooks 目录：{error}") from error
    return path


def remove_tree(path: Path) -> str | None:
    """删除一棵目录树；返回 None 表示删干净了，否则返回失败的原因。

    Windows 上 Git pack 文件可能只读；删除失败时摘掉只读位重试。
    staging 和回收目录的调用方各自决定如何报告残留。
    """
    if not os.path.lexists(path):
        return None
    try:
        shutil.rmtree(path, onexc=_clear_read_only)
    except OSError as error:
        return str(error)
    return None


def _clear_read_only(function: Callable[..., object], path: str, _error: BaseException) -> None:
    """rmtree 的失败处理器：摘掉只读位后把同一个动作重试一次。

    同时保留读位，避免在 POSIX 上把权限改成 0200。
    """
    Path(path).chmod(stat.S_IWRITE | stat.S_IREAD)
    function(path)


def _remove(path: Path) -> None:
    """尽力清理一个事务目录；删不掉的残留只留在磁盘上，不改变主错误。

    这一段跑在 finally 里，抛出去只会盖掉真正的失败原因。删不掉的原因由
    ``remove_tree`` 负责排除，这里只是不把它变成新的异常。
    """
    remove_tree(path)


__all__ = [
    "GIT_CLONE_TIMEOUT_SECONDS",
    "MIN_COMMIT_LENGTH",
    "STAGE_PREFIX",
    "CapturedProcessRunner",
    "Cloner",
    "GitRepositoryCloner",
    "ProcessResult",
    "ProcessRunner",
    "Staging",
    "check_clone_url",
    "check_commit",
    "check_repository_name",
    "github_https_path",
    "isolated_git_environment",
    "normalize_repository_input",
    "remove_tree",
    "staging_directory",
]
