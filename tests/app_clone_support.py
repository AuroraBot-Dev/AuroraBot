"""clone 与 GitHub 测试的共享辅助：假进程、假 GitHub、假 clone 与仓库夹具。

沿用 ``app_search_support.py`` 建立的惯例：文件名不以 ``test_`` 开头，pytest
不收集它，覆盖率也只统计 ``aurora`` 与 ``aurorabot``。

只放 fake、fixture 与 builder，不复制生产业务规则 —— 一份规则若在这里有第二个
实现，那它就没被任何测试真正验证过。所以 ``FakeProcessRunner`` 不模拟 git 的
行为、也不生成 HEAD：它只记录 argv 与 env、返回预置结果；``FakeCloner`` 也不
模拟 git，它只回答「clone 成功之后 staging 里应该有什么」，那是 fixture 的活。
提交摘要使用固定的合法四十位十六进制值，结果无需依赖本机 Git 仓库。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx2
from app_search_support import FakeTransport

from aurora.commands.app.clone import ProcessResult
from aurora.commands.app.models import CloneResult, Repository

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from aurora.commands.app.clone import Staging

DEFAULT_COMMIT = "3f2a1c9d4e5b6a7c8d9e0f1a2b3c4d5e6f7a8b9c"
APP_PACKAGE = "github.churk-ben.aurora-qq"
APP_PATH = "extensions/apps/Churk-Ben/Aurora-QQ"
APPS_DIRECTORY = ("extensions", "apps")
CONFLICTING_PACKAGE = "com.example.occupied"


class FakeProcessRunner:
    """替掉子进程边界；记录每次调用的 argv、cwd、timeout 与 env。"""

    def __init__(self, *results: ProcessResult | Exception) -> None:
        self.results = list(results)
        self.calls: list[dict[str, Any]] = []

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        timeout: float,
        env: Mapping[str, str] | None = None,
    ) -> ProcessResult:
        self.calls.append({"command": [str(item) for item in command], "cwd": cwd, "timeout": timeout, "env": env})
        if not self.results:
            raise AssertionError("FakeProcessRunner 收到的调用多于预置结果")
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def argv(self, index: int = 0) -> list[str]:
        """第 index 次调用的 argv。"""
        command: Sequence[str] = self.calls[index]["command"]
        return list(command)

    def environment(self, index: int = 0) -> Mapping[str, str]:
        """第 index 次调用注入的环境；没传 env 就直接失败。"""
        environment = self.calls[index]["env"]
        assert environment is not None, "这次调用没有传 env"
        return environment


def cloning_runner(*, commit: str = DEFAULT_COMMIT) -> FakeProcessRunner:
    """一次成功的 clone + rev-parse；clone 只产出一行普通 stderr。"""
    return FakeProcessRunner(
        ProcessResult(0, "", "Cloning into 'apps'...\n"),
        ProcessResult(0, f"{commit}\n", ""),
    )


class FakeCloner:
    """替掉 Git 边界；往 staging 里铺一份预置仓库内容并回报一次成功的 clone。"""

    def __init__(
        self,
        files: Mapping[str, str] | None = None,
        *,
        commit: str = DEFAULT_COMMIT,
        failure: Exception | None = None,
    ) -> None:
        self.files = dict(files or {})
        self.commit = commit
        self.failure = failure
        self.calls: list[dict[str, Any]] = []
        self.roots: list[Path] = []

    def clone(self, repository: Repository, target: Staging, *, ref: str | None = None) -> CloneResult:
        self.calls.append({"repository": repository.full_name, "ref": ref, "root": target.root})
        if self.failure is not None:
            raise type(self.failure)(str(self.failure)) from None
        self.roots.append(target.root)
        for relative, content in self.files.items():
            path = target.root.joinpath(*relative.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return CloneResult(
            repository=repository.full_name,
            path=target.root,
            ref=ref or repository.default_branch,
            commit=self.commit,
        )


def repository(full_name: str = "Churk-Ben/Aurora-QQ", **overrides: object) -> Repository:
    """一个可安装的仓库；``full_name`` 与 ``clone_url`` 默认保持一致。"""
    owner, _, name = full_name.partition("/")
    fields: dict[str, Any] = {
        "full_name": full_name,
        "owner": owner,
        "name": name,
        "description": "QQ 通知 App",
        "stars": 12,
        "topics": ("aurorabot-app",),
        "updated_at": "2026-09-01T12:00:00Z",
        "default_branch": "main",
        "html_url": f"https://github.com/{full_name}",
        "clone_url": f"https://github.com/{full_name}.git",
        "archived": False,
        "disabled": False,
    }
    fields.update(overrides)
    return Repository(**fields)


def repository_payload(full_name: str = "Churk-Ben/Aurora-QQ", **overrides: object) -> dict[str, object]:
    """``GET /repos/{owner}/{repo}`` 的一份合法响应体，与搜索条目的字段同形。"""
    owner, _, name = full_name.partition("/")
    payload: dict[str, object] = {
        "full_name": full_name,
        "name": name,
        "description": "QQ 通知 App",
        "stargazers_count": 12,
        "topics": ["aurorabot-app"],
        "updated_at": "2026-09-01T12:00:00Z",
        "default_branch": "main",
        "html_url": f"https://github.com/{full_name}",
        "clone_url": f"https://github.com/{full_name}.git",
        "archived": False,
        "disabled": False,
        "owner": {"login": owner},
    }
    payload.update(overrides)
    return payload


def transport(*payloads: Mapping[str, object]) -> FakeTransport:
    """真实 ``GitHubSource`` + 假 transport：仓库接口依次返回预置响应体。"""
    return FakeTransport(*[httpx2.Response(200, json=dict(payload)) for payload in payloads])


def project(tmp_path: Path, apps_toml: str | None = None) -> Path:
    """一个最小项目根；给了内容就顺手写一份 ``config/apps.toml``。"""
    if apps_toml is not None:
        config = tmp_path / "config"
        config.mkdir(parents=True, exist_ok=True)
        (config / "apps.toml").write_text(apps_toml, encoding="utf-8")
    return tmp_path


def apps_root(project_root: Path) -> Path:
    return project_root.joinpath(*APPS_DIRECTORY)


def apps_root_entries(project_root: Path) -> list[str]:
    """安装根目录下的残留项；第三阶段成功与失败之后都要求它是空的。"""
    root = apps_root(project_root)
    if not root.is_dir():
        return []
    return sorted(entry.name for entry in root.iterdir())


def registry_entry(package: str = CONFLICTING_PACKAGE, working_dir: str = APP_PATH) -> str:
    """一条注册表记录，用来制造 package 冲突。"""
    return (
        f'[[app]]\npackage = "{package}"\nenabled = false\ntransport = "stdio"\n'
        f'working_dir = "{working_dir}"\ncommand = ["uv", "run", "demo"]\nenv = []\n'
        'timeout_seconds = 60\nevent_mode = "disabled"\n'
    )
