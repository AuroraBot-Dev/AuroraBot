"""提交 App 的安装与移除，并在失败时回滚文件变更。"""

from __future__ import annotations

import configparser
import os
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from aurora.commands.app.clone import github_https_path, remove_tree
from aurora.commands.app.install import (
    APPS_DIRECTORY,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_TRANSPORT,
    check_final_path,
    check_package_collision,
    project_path,
)
from aurora.commands.app.models import (
    AppNotFoundError,
    ConnectPlan,
    InstallError,
    RawApp,
    RemoveError,
    RunnerPlan,
)
from aurora.commands.app.store import check_project_directory
from aurorabot.mcp.config import AppConfig
from aurorabot.utils.validation import check_relative_directory

if TYPE_CHECKING:
    from aurora.commands.app.install import PreparedInstall
    from aurora.commands.app.models import AppPlan, InstallPlan
    from aurora.commands.app.store import AppStore

REMOVE_PREFIX = ".aurora-remove-"
_ORIGIN_SECTION = 'remote "origin"'


@dataclass(frozen=True, slots=True)
class Removal:
    """一次移除的目标：package 与要删的受管根（非受管时为 None）。

    ``force`` 随目标一起带着走，因为提交前要重做一次与 ``plan_removal`` 完全相同的
    判断：归属校验是否被用户显式放弃，是那次判断的一部分，而不是调用方记得住的
    事。
    """

    package: str
    managed_root: Path | None
    force: bool = False


def classify_managed_app(project_root: Path, entry: RawApp) -> Path | None:
    """按路径形状推导受管安装根；不是受管形状时返回 None。

    受管 = Aurora 自己安装出来的 App，正式路径 ``extensions/apps/<owner>/<repo>``。
    working_dir 落不到这层之下的条目一律非受管，remove 只解除注册。

    段数够时取前两段而不是整条 working_dir：``repository_subdir`` 不为 ``.`` 时
    working_dir 会多出一层（``extensions/apps/owner/repo/apps/server``），而
    remove 要删的是仓库根，不是最后那个子目录。

    只判形状，不判安全：链接与越界归 ``check_project_directory``。两者失败的
    含义不同 —— 一个是「不该删」，一个是「不能删」。
    路径校验将反斜杠视为分隔符并拒绝绝对路径与父目录段，再按大小写敏感的目录段判断安装根。
    """
    if entry.working_dir is None:
        return None
    try:
        check_relative_directory(entry.working_dir, "app.working_dir")
    except ValueError:
        return None
    parts = PurePosixPath(entry.working_dir.replace("\\", "/")).parts
    if parts[: len(APPS_DIRECTORY)] != APPS_DIRECTORY or len(parts) < len(APPS_DIRECTORY) + 2:
        return None
    return project_root.joinpath(*parts[: len(APPS_DIRECTORY) + 2])


def plan_removal(store: AppStore, entry: RawApp, *, force: bool) -> Removal:
    """判定一个条目该怎么移除：受管根、路径安全与 origin 归属。

    计划时先算一次以尽早失败；提交前重算，因为用户可能在这段时间改过目录
    或 ``.git/config``。
    """
    root = classify_managed_app(store.project_root, entry)
    if root is None:
        return Removal(entry.package, None, force)
    check_project_directory(store.project_root, root, "受管安装目录")
    if not force:
        check_managed_ownership(store.project_root, root, entry.package)
    return Removal(entry.package, root, force)


def check_managed_ownership(project_root: Path, root: Path, package: str) -> None:
    """确认这个受管目录确实来自它路径所声称的那个仓库。

    仅凭目录位于 ``extensions/apps/`` 不足以证明 Aurora 可以删除它。期望值来自
    目录名而不是 package：``--package`` 可以把 package 改成任意名字，目录名才是
    仓库身份的痕迹。

    ``--force`` 放宽的正是这一条，而且只有这一条 —— 路径边界不由用户参数开启。
    """
    expected = f"{root.parent.name}/{root.name}"
    origin = read_origin(root)
    actual = None if origin is None else github_https_path(origin)
    if actual is not None and actual.lower() == expected.lower():
        return
    detail = "读不到 .git/config 里的 origin" if origin is None else f"origin 指向 {origin}"
    raise RemoveError(
        f"无法确认 {relative_path(project_root, root)} 由 Aurora 安装（package {package}）：\n"
        f"  {detail}，与目录名声明的 {expected} 不符。\n"
        f"如仍要删除这个目录，请加 --force。"
    )


def read_origin(root: Path) -> str | None:
    """从 ``<root>/.git/config`` 里取 origin 的 URL；读不出来就返回 None。

    ``.git/config`` 是第三方内容：缺失、没有 remote、没有 origin、不是合法
    INI，一律当作「校验失败」，不是崩溃。
    """
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        with (root / ".git" / "config").open("r", encoding="utf-8", errors="replace") as stream:
            parser.read_file(stream)
    except (OSError, configparser.Error):
        return None
    if not parser.has_option(_ORIGIN_SECTION, "url"):
        return None
    return parser.get(_ORIGIN_SECTION, "url").strip() or None


def install_transaction(store: AppStore, prepared: PreparedInstall) -> None:
    """一次安装提交：发布目录、原子写注册表，失败时搬回目录。

    顺序是先文件系统后注册表：反过来的话，目录搬不过去时会短暂留下「注册了但
    目录不存在」，而那正是 ``aurora start`` 会读到并尝试启动的状态。先搬目录、
    注册表写失败则可以搬回去，用户什么也看不到。
    """
    plan = prepared.plan
    staging_root = prepared.staging.root

    revalidate_install(store, plan)
    destination = project_path(store.project_root, plan.install_path)
    owner = _create_owner_directory(destination)
    published = False
    try:
        _publish(staging_root, destination)
        published = True
        store.add_app(registry_entry(plan))
    except BaseException as error:
        residue = _undo_install(staging_root, destination, published=published, owner=owner)
        if residue is None:
            raise
        raise InstallError(_install_residue(store.project_root, residue)) from error


def remove_transaction(store: AppStore, removal: Removal) -> None:
    """一次移除提交：搬到回收目录、原子写注册表，再删除回收目录。

    受管 App 先把正式目录搬到回收目录，注册表写成功之后才真删：``rmtree`` 没有
    回头路，而 rename 有。非受管 App 跳过搬目录，只删注册表条目。
    """
    quarantine: Path | None = None

    revalidate_remove(store, removal)
    quarantine = _quarantine(store.project_root, removal)
    try:
        store.remove_app(removal.package)
    except BaseException as error:
        residue = _undo_remove(removal, quarantine)
        if residue is None:
            raise
        raise RemoveError(_remove_residue(store.project_root, removal.package, residue)) from error
    _discard_quarantine(store.project_root, removal, quarantine)


def revalidate_install(store: AppStore, plan: InstallPlan) -> None:
    """提交前重新确认 package 与目标路径仍然可用。

    计划阶段的 preflight 与这里之间隔着 clone、检测、展示、用户思考与 verify，
    几十秒到几分钟。期间用户可能改过注册表或目标目录。
    """
    check_package_collision(store, plan.package)
    check_project_directory(store.project_root, project_path(store.project_root, plan.install_path), "安装目录")
    check_final_path(store.project_root, plan.install_path)


def revalidate_remove(store: AppStore, removal: Removal) -> None:
    """提交前重做整次移除判定；与 ``revalidate_install`` 对称。

    重读的是注册表本身而不是调用方手里那份快照：从判定到提交之间，
    用户可能已经改过这条配置。

    归属校验也在这里重做一遍：它读的是 ``.git/config``，也就是一个用户随时可能
    在文件管理器里改动的第三方文件。前一次只负责尽早失败，提交前以这次检查为准。
    """
    entry = store.raw_app(removal.package)
    if entry is None:
        raise AppNotFoundError(f"注册表中不存在 package：{removal.package}")
    if removal.managed_root is None:
        return
    check_project_directory(store.project_root, removal.managed_root, "受管安装目录")
    if classify_managed_app(store.project_root, entry) != removal.managed_root:
        changed = relative_path(store.project_root, removal.managed_root)
        raise RemoveError(f"受管安装目录在判定之后发生了变化：{changed}")
    if not removal.force:
        check_managed_ownership(store.project_root, removal.managed_root, removal.package)


def registry_entry(plan: AppPlan) -> AppConfig:
    """把计划投影成注册表条目；这是「计划 → 配置」唯一的一处翻译。

    env 恒为 ``[]``：不扫 README 猜环境变量、不保存 secret，也不把 os.environ
    全量传给第三方 Server。远程条目的凭据同样只是一个变量名 —— ``auth_env``
    存的是名字，值永远留在用户自己的环境里。

    注册表的字段是封闭白名单，多写一个 key 会让 ``aurora start`` 直接拒绝整个
    文件，所以这里也顺手保证了「计划里有什么，注册表里就有什么」。
    源码和包管理器计划共用本地条目，均显式记录工作目录与启动命令。
    """
    if isinstance(plan, ConnectPlan):
        return AppConfig(
            package=plan.package,
            enabled=plan.enabled,
            transport="streamable_http",
            event_mode=plan.event_mode,
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
            url=plan.url,
            auth_env=plan.auth_env,
        )
    return AppConfig(
        package=plan.package,
        enabled=plan.enabled,
        transport=DEFAULT_TRANSPORT,
        event_mode=plan.event_mode,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        working_dir=plan.working_dir,
        command=plan.command,
        env=(),
    )


def register_transaction(store: AppStore, plan: RunnerPlan | ConnectPlan) -> None:
    """一次纯注册表登记：不搬任何目录，因此没有可回滚的东西。

    ``connect`` 与 ``--npx`` / ``--uvx`` 都不产生 Aurora 拥有的文件：包在包管理器
    的缓存里，远程 Server 在别人那儿。所以这里只做「再查一次重名」与
    ``add_app`` 的原子写 —— 写失败时原文件不变，用户什么也看不到。
    """
    check_package_collision(store, plan.package)
    store.add_app(registry_entry(plan))


def _create_owner_directory(destination: Path) -> Path | None:
    """建 owner 级目录，返回「这一级是这次新建的」的那个路径。

    这不是优化：第一次安装某个 owner 时 ``extensions/apps/<owner>/`` 不存在，
    而 rename 的目标父目录缺失会直接失败。回滚时要把它一并删掉，所以必须记住
    是不是自己建的。
    """
    owner = destination.parent
    if owner.is_dir():
        return None
    try:
        owner.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise InstallError(f"无法创建安装目录 {owner}：{error}") from error
    return owner


def _publish(source: Path, destination: Path) -> None:
    """同文件系统内的近似原子搬迁。

    不需要 copy + delete：安装根下的两个路径本来就在同一个文件系统上，而复制
    到一半失败会留下一个半成品的正式目录。
    """
    try:
        source.replace(destination)
    except OSError as error:
        raise InstallError(f"无法把安装目录移动到 {destination}：{error}") from error


def _undo_install(staging_root: Path, destination: Path, *, published: bool, owner: Path | None) -> Path | None:
    """撤销已发布目录并返回无法回收的残留；新建父目录非空时保留，以免影响并发安装。"""
    if published and os.path.lexists(destination):
        try:
            destination.replace(staging_root)
        except OSError:
            return destination
    if owner is not None and os.path.lexists(owner):
        with suppress(OSError):
            owner.rmdir()
    return None


def _quarantine(project_root: Path, removal: Removal) -> Path | None:
    """把受管目录搬到一个中间名字；非受管 App 不碰任何文件。

    rename 的目标就是回收目录本身，不需要预先 mkdir：rename 会把整个目录变成
    那个名字。前缀与 staging 同源，都是 ``.aurora-`` 系列，因此都不适用「恰好
    两级」那条注册 App 路径规则。
    """
    if removal.managed_root is None:
        return None
    quarantine = project_root.joinpath(*APPS_DIRECTORY) / f"{REMOVE_PREFIX}{uuid.uuid4().hex}"
    try:
        removal.managed_root.replace(quarantine)
    except OSError as error:
        moved = relative_path(project_root, removal.managed_root)
        raise RemoveError(f"无法把 {moved} 移入回收目录：{error}") from error
    return quarantine


def _undo_remove(removal: Removal, quarantine: Path | None) -> Path | None:
    """把回收目录搬回正式路径；返回没能搬回去的回收目录（搬回去了就是 None）。"""
    if quarantine is None or removal.managed_root is None:
        return None
    try:
        quarantine.replace(removal.managed_root)
    except OSError:
        return quarantine
    return None


def _discard_quarantine(project_root: Path, removal: Removal, quarantine: Path | None) -> None:
    """删除回收目录；失败只报告，不回滚注册表。

    注册表删除成功、目录删不掉时，从逻辑上讲 remove 已经完成：注册表里没有
    这个 package，正式路径上也没有这个目录。不为了清理失败把条目写回来 ——
    写回会让用户得到一个指向「已经移走、但还在磁盘上某处」的条目，比残留一个
    目录更糟。
    只有同时存在受管根与回收目录时才执行清理，并在错误中列出两条路径。
    """
    managed_root = removal.managed_root
    if quarantine is None or managed_root is None:
        return
    residue = remove_tree(quarantine)
    if residue is not None:
        raise RemoveError(
            f"注册表已更新，{removal.package} 已移除，但残留目录未能删除：\n"
            f"  残留目录：{relative_path(project_root, quarantine)}\n"
            f"  原正式路径：{relative_path(project_root, managed_root)}\n"
            f"  {residue}\n"
            f"重跑 remove 只会得到「package 不存在」，请手动删除残留目录。"
        )


def _install_residue(project_root: Path, residue: Path) -> str:
    """回滚没能完成时的报告：注册表状态 + 确切残留路径。"""
    return (
        f"安装失败，且自动回滚未能完成。\n"
        f"  残留目录：{relative_path(project_root, residue)}\n"
        f"  注册表未修改。\n"
        f"请手动删除残留目录后重试。"
    )


def _remove_residue(project_root: Path, package: str, residue: Path) -> str:
    """回收回滚失败时的报告；残留的 UUID 目录必须说清它原来是哪一个。"""
    return (
        f"移除失败，且自动回滚未能完成。\n"
        f"  残留目录：{relative_path(project_root, residue)}\n"
        f"  注册表未修改，{package} 仍在。\n"
        f"请手动把残留目录改回原路径后重试。"
    )


def relative_path(project_root: Path, path: Path) -> str:
    """展示用的路径一律写成项目内相对形式：绝对路径在别人的机器上没法照着操作。"""
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return str(path)


__all__ = [
    "REMOVE_PREFIX",
    "Removal",
    "check_managed_ownership",
    "classify_managed_app",
    "install_transaction",
    "plan_removal",
    "read_origin",
    "register_transaction",
    "registry_entry",
    "relative_path",
    "remove_transaction",
    "revalidate_install",
    "revalidate_remove",
]
