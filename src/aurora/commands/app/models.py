"""``aurora app`` 的纯值对象、错误体系与输入校验。

源码、包管理器和远程连接计划分别保存各自的来源，共用登记状态与工具目录。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from aurorabot.utils.validation import check_package_name

if TYPE_CHECKING:
    from pathlib import Path

    from aurorabot.mcp.config import AppConfig, McpEventMode

type AppState = Literal["ready", "missing", "invalid", "configured"]
type AppKind = Literal["local", "remote"]
type RepositoryStatus = Literal["active", "archived", "disabled"]

_SECRET_HINTS = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "API_KEY", "APIKEY", "AUTH")


def is_secret_name(name: str) -> bool:
    """按名称识别凭据字段，供诊断脱敏和连接 URL 校验共用，不检查凭据值的形状。"""
    upper = name.upper()
    return any(hint in upper for hint in _SECRET_HINTS)


class AppError(RuntimeError):
    """可直接转换为中文 CLI 失败结果的 App 管理错误。"""


class ConfigError(AppError):
    """输入或配置不合法：注册表缺失或无法解析，或命令行参数越界。"""


class RegistryError(AppError):
    """注册表结构不合法，例如 app 不是表数组，或 package 缺失、非法、重复。"""


class RegistryWriteError(RegistryError):
    """注册表写入失败；原文件保持不变。"""


class PackageError(AppError):
    """package ID 不是小写点分包名。"""


class AppNotFoundError(AppError):
    """注册表中不存在该 package。"""


class PathError(AppError):
    """working_dir 不是可安全使用的项目内路径。"""


class DiscoveryError(AppError):
    """GitHub 仓库发现失败。

    消息里绝不允许出现请求头、``Authorization`` 或 token：错误信息会被直接打印
    给用户，也会被贴进 issue。
    """


class GitHubRateLimitError(DiscoveryError):
    """GitHub API 配额耗尽；携带重置时间或 Retry-After。"""


class CloneError(AppError):
    """Git 操作失败：git 不存在、clone 超时、网络失败或非零退出。

    独立于 ``DiscoveryError``：clone 是有副作用的一步，不是发现，退出码也属于
    一般失败。消息里同样不允许出现环境变量、token 或 ``Authorization``。
    """


class PlanError(AppError):
    """仓库准入、package、路径或启动命令不符合安装要求。"""


class ManifestError(PlanError):
    """仓库清单缺失或内容不符合 Aurora 的启动契约。"""


class InstallError(AppError):
    """安装提交或回滚失败：文件系统没能落到预期状态。

    与 ``PlanError`` 的分界是「输入是否合法」：计划本身没问题，执行到一半
    （建目录、rename、原子写）失败，就是一般失败。消息里必须给出确切的残留
    路径 —— 那是用户唯一能自己动手的地方。
    """


class RemoveError(AppError):
    """移除提交或回滚失败：文件系统没能落到预期状态。

    与 ``InstallError`` 分开而不是合成一个事务错误：两者要指出的残留不同
    （安装是正式目录，移除是回收目录），而「现在磁盘上剩下什么」正是用户
    最需要知道的那句话。
    """


class VerifyError(AppError):
    """MCP 连接、工具发现或关闭失败；错误摘要遮蔽已知的敏感变量值。"""


@dataclass(frozen=True, slots=True)
class RawApp:
    """注册表里某一条目的原始声明。

    ``working_dir`` 是 TOML 里写的那个字符串（缺失、空白或类型不对时为 None），
    ``config`` 是它能否被运行时配置读取器接受。两者必须分开：remove 需要知道
    「用户写了什么」以及「它能不能安全使用」，而列表投影（``AppListItem``）
    把前者的无效情形压成了展示用占位符，信息已经丢了。
    """

    package: str
    working_dir: str | None
    config: AppConfig | None


@dataclass(frozen=True, slots=True)
class AppListItem:
    """注册表条目的展示状态；``ready`` 只表示本地工作目录存在。"""

    package: str
    enabled: bool
    transport: str
    state: AppState
    path: str | None

    @property
    def kind(self) -> AppKind:
        """这一条是本地进程还是远程端点。

        由 transport 推导，不新增注册表字段：两者的对应关系是 1:1（stdio 即本地，
        streamable_http 即远程），而注册表的字段集是运行时封闭白名单。列出来只是
        为了让「本地装出来的」与「连过去的」在终端里一眼可分。
        """
        return "remote" if self.transport == "streamable_http" else "local"


@dataclass(frozen=True, slots=True)
class AppList:
    """一次注册表读取的结果。"""

    apps: tuple[AppListItem, ...]


@dataclass(frozen=True, slots=True)
class Repository:
    """GitHub 上的一个候选仓库。

    带 aurorabot-app topic 只说明它是候选，不说明它是 MCP Server：发现阶段不
    clone、不检查、不连接。字段集覆盖 install 真正需要的部分。
    """

    full_name: str
    owner: str
    name: str
    description: str | None
    stars: int
    topics: tuple[str, ...]
    updated_at: str
    default_branch: str
    html_url: str
    clone_url: str
    archived: bool
    disabled: bool

    @property
    def status(self) -> RepositoryStatus:
        """展示用状态；被禁用优先于被归档，两者都不适合安装。"""
        if self.disabled:
            return "disabled"
        return "archived" if self.archived else "active"


@dataclass(frozen=True, slots=True)
class RepositoryPage:
    """一页 GitHub 搜索结果。"""

    items: tuple[Repository, ...]
    page: int
    page_size: int
    total_count: int
    incomplete_results: bool


@dataclass(frozen=True, slots=True)
class CloneResult:
    """成功克隆后的检出引用、HEAD commit 与目录。"""

    repository: str
    path: Path
    ref: str
    commit: str


@dataclass(frozen=True, slots=True)
class LaunchCandidate:
    """清单或 ``--command`` 指定的入口；``evidence`` 记录出处。"""

    command: tuple[str, ...]
    runtime: str
    evidence: str
    repository_subdir: str = "."


@dataclass(frozen=True, slots=True)
class RunnerPlan:
    """包管理器安装计划；``tools`` 只用于展示，运行期会重新发现。"""

    package: str
    command: tuple[str, ...]
    runtime: str
    working_dir: str
    enabled: bool = False
    tools: tuple[str, ...] = ()
    event_mode: McpEventMode = "disabled"


@dataclass(frozen=True, slots=True)
class ConnectPlan:
    """远程 URL 安装计划；不含本地命令与工作目录。"""

    package: str
    url: str
    auth_env: str | None = None
    enabled: bool = False
    tools: tuple[str, ...] = ()
    event_mode: McpEventMode = "disabled"


@dataclass(frozen=True, slots=True)
class InstallPlan:
    """源码安装的仓库、启动命令和注册表字段；暂存目录由调用方单独持有。"""

    repository: str
    ref: str
    commit: str
    package: str
    install_path: str
    repository_subdir: str
    working_dir: str
    transport: str
    command: tuple[str, ...]
    runtime: str
    evidence: str
    enabled: bool = False
    tools: tuple[str, ...] = ()
    event_mode: McpEventMode = "disabled"


type AppPlan = InstallPlan | RunnerPlan | ConnectPlan


def validate_package(value: str) -> str:
    """校验并返回 package ID；与运行时 AppConfig 使用同一条包名规则。"""
    try:
        check_package_name(value, "app.package")
    except ValueError as error:
        raise PackageError(f"package ID 必须是小写点分包名：{value}") from error
    return value


def registry_package(value: object, label: str) -> str:
    """校验注册表里的 package 字段；package 本身的问题让整次读取失败。"""
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(f"{label} 的 package 必须是非空文本")
    try:
        return validate_package(value.strip())
    except PackageError as error:
        raise RegistryError(f"{label} 的 {error}") from error


__all__ = [
    "AppError",
    "AppKind",
    "AppList",
    "AppListItem",
    "AppNotFoundError",
    "AppPlan",
    "AppState",
    "CloneError",
    "CloneResult",
    "ConfigError",
    "ConnectPlan",
    "DiscoveryError",
    "GitHubRateLimitError",
    "InstallError",
    "InstallPlan",
    "LaunchCandidate",
    "ManifestError",
    "PackageError",
    "PathError",
    "PlanError",
    "RawApp",
    "RegistryError",
    "RegistryWriteError",
    "RemoveError",
    "Repository",
    "RepositoryPage",
    "RepositoryStatus",
    "RunnerPlan",
    "VerifyError",
    "is_secret_name",
    "registry_package",
    "validate_package",
]
