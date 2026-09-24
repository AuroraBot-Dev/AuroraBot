"""安装用例测试的共享辅助：假 MCP 工厂、``aurora-app.toml`` 与计划夹具。

沿用 ``app_clone_support.py`` 建立的惯例：文件名不以 ``test_`` 开头，pytest 不
收集它，覆盖率也只统计 ``aurora`` 与 ``src``。

只放 fake、fixture 与 builder，不复制生产业务规则 —— 一份规则若在这里有第二个
实现，那它就没被任何测试真正验证过。``FakeMcpClientFactory`` 不模拟 MCP：它只
回答「按这份 spec 打开连接会成功还是抛什么」，握手到底是几个来回是 ``src/mcp``
的事。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from app_clone_support import FakeCloner, repository

from aurora.commands import app as app_module
from aurora.commands.app.clone import Staging
from aurora.commands.app.manifest import MANIFEST_NAME, MANIFEST_VERSION
from aurora.commands.app.models import InstallPlan, LaunchCandidate, Repository
from aurora.commands.app.verify import MCPVerifier
from src.mcp.models import McpRemoteTool, McpToolsPage

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence
    from pathlib import Path
    from typing import Any

    import pytest

    from aurora.commands.app.github import GitHubSource
    from aurora.commands.app.service import AppManager
    from aurora.commands.app.store import AppStore
    from src.mcp.client import CatalogChangedHandler, DisconnectedHandler, McpCallResult, McpClientPort
    from src.mcp.events import InboundEventHandler, McpInboundEvent
    from src.mcp.models import McpAppSpec

# 一个合法的 40 位十六进制 HEAD，与 app_clone_support 同源。
DEFAULT_COMMIT = "3f2a1c9d4e5b6a7c8d9e0f1a2b3c4d5e6f7a8b9c"
DEFAULT_PROTOCOL = "2025-06-18"
WEATHER_PACKAGE = "github.example.weather-mcp"
WEATHER_PATH = "extensions/apps/example/weather-mcp"
WEATHER_COMMAND = ("uv", "run", "weather-mcp")
MANIFEST_EVIDENCE = f"{MANIFEST_NAME} [server].command"
# 远程端点的准入测试反复用到的一个地址。
ENDPOINT = "https://mcp.example.com/rpc"
ENDPOINT_PACKAGE = "com.example.remote"
# 假 Server 默认暴露的一个工具：安装检查要求「至少一个可注册工具」，所以默认
# 必须有内容，否则每个用例都得先声明自己要装的东西有工具。
DEFAULT_TOOL_NAMES = ("weather_now",)
# 授权测试默认引用的 Agent：``config.example/agents.toml`` 里真实存在的一个 ID。
DEFAULT_AGENT_ID = "builtin.worker"
# 一个可注册工具的领域 ID 前缀由发现规则决定：``aur.mcp.<package>.<raw_name>``。
DEFAULT_TOOL_PREFIX = "aur.mcp."


def tools_page(names: Sequence[str] = DEFAULT_TOOL_NAMES, *, next_cursor: str | None = None) -> McpToolsPage:
    """一页 ``tools/list`` 结果；schema 恒为合法的 object。"""
    return McpToolsPage(
        tools=tuple(
            McpRemoteTool(name=name, description=f"{name} 说明", input_schema={"type": "object", "properties": {}})
            for name in names
        ),
        next_cursor=next_cursor,
    )


def manifest_text(
    command: Sequence[str] = WEATHER_COMMAND,
    *,
    version: int = MANIFEST_VERSION,
    extra: str = "",
) -> str:
    """一份最小可用的 ``aurora-app.toml``；``version``/``extra`` 用来造不合规的清单。"""
    argv = ", ".join(f'"{item}"' for item in command)
    return f"manifest_version = {version}\n\n[server]\ncommand = [{argv}]\n{extra}"


# 默认清单一：所有需要「仓库声明了怎么启动」的用例都拿它当输入。
MANIFEST = manifest_text()


class FakeMcpPort:
    """``McpClientPort`` 的替身：只实现安装检查真正会碰的那几个成员。

    其余成员一律断言失败而不是静默返回空值 —— 一个能悄悄通过的类型完整的假端口
    会让「检查忽然开始调用工具」这种回归在测试里看不出来。fake 不需要模拟 MCP，
    但必须对「被用到了不该用的东西」有反应。

    ``pages`` 是预置的 ``tools/list`` 分页结果，按 cursor 顺序逐次返回；它让
    「分页发现」与「非法响应」都能在没有真实 Server 的情况下被驱动。
    """

    def __init__(
        self,
        *,
        protocol_version: str = DEFAULT_PROTOCOL,
        connected: bool = True,
        pages: Sequence[McpToolsPage] | None = None,
        list_failure: Exception | None = None,
    ) -> None:
        self._protocol_version = protocol_version
        self._connected = connected
        self._pages = tuple(pages) if pages is not None else (tools_page(),)
        self._list_failure = list_failure
        self.cursors: list[str | None] = []
        self.closed = False

    @property
    def protocol_version(self) -> str:
        if self.closed:
            raise RuntimeError("Client must be used within an async context manager")
        return self._protocol_version

    @property
    def connected(self) -> bool:
        return self._connected

    async def close(self) -> None:
        self.closed = True

    async def list_tools(self, *, cursor: str | None = None) -> McpToolsPage:
        self.cursors.append(cursor)
        if self._list_failure is not None:
            raise self._list_failure
        return self._pages[len(self.cursors) - 1]

    async def call_tool(self, name: str, arguments: Mapping[str, Any], timeout_seconds: float) -> McpCallResult:
        raise AssertionError("安装检查不应该调用工具")

    async def bind_observers(
        self,
        *,
        catalog_changed: CatalogChangedHandler,
        disconnected: DisconnectedHandler,
    ) -> None:
        raise AssertionError("安装检查不应该订阅目录变化")

    def activate_events(self) -> None:
        raise AssertionError("安装检查不应该激活事件")

    def deactivate_events(self) -> None:
        raise AssertionError("安装检查不应该激活事件")


class FakeMcpClientFactory:
    """替掉 MCP 边界；记录每次 ``open`` 收到的 spec，按预置结果回答。

    超时不是靠真实等待实现的：``hang=True`` 时 ``open`` 永不返回，由被测代码的
    外层 ``asyncio.wait_for`` 负责把它变成 TimeoutError。测试因此不必等满
    ``timeout_seconds``，也不必去改生产代码里的常量。
    """

    def __init__(
        self,
        *,
        protocol_version: str = DEFAULT_PROTOCOL,
        connected: bool = True,
        failure: Exception | None = None,
        hang: bool = False,
        close_failure: Exception | None = None,
        tools: Sequence[str] = DEFAULT_TOOL_NAMES,
        pages: Sequence[McpToolsPage] | None = None,
        list_failure: Exception | None = None,
    ) -> None:
        self.protocol_version = protocol_version
        self.connected = connected
        self.failure = failure
        self.hang = hang
        self.close_failure = close_failure
        # pages 优先于 tools：分页与非法响应需要自己指定每一页。
        self.pages = tuple(pages) if pages is not None else (tools_page(tools),)
        self.list_failure = list_failure
        self.specs: list[McpAppSpec] = []
        self.handlers: list[InboundEventHandler] = []
        self.ports: list[FakeMcpPort] = []

    async def open(self, spec: McpAppSpec, event_handler: InboundEventHandler) -> McpClientPort:
        self.specs.append(spec)
        self.handlers.append(event_handler)
        if self.hang:
            await asyncio.Event().wait()
        if self.failure is not None:
            raise self.failure
        port = FakeMcpPort(
            protocol_version=self.protocol_version,
            connected=self.connected,
            pages=self.pages,
            list_failure=self.list_failure,
        )
        if self.close_failure is not None:
            port.close = _raiser(self.close_failure)  # type: ignore[method-assign]
        self.ports.append(port)
        return port

    def spec(self, index: int = 0) -> McpAppSpec:
        """第 index 次打开连接时收到的 spec。"""
        return self.specs[index]


def _raiser(error: Exception) -> Callable[[], Awaitable[None]]:
    """一个总是抛 ``error`` 的 async 函数，用来替掉 port.close。"""

    async def close() -> None:
        raise error

    return close


class FakeSource:
    """替掉整个 GitHub 路径：仓库接口与清单接口各自返回预置事实。

    ``AppManager`` 只在这三个方法上和 ``GitHubSource`` 打交道，所以替身不必实现
    transport 那一层；install 用的是 ``repository`` 与 ``manifest``，被调 ``search``
    就是测试写错了。

    ``manifest=None`` 表示这个仓库没有清单（真实实现里是 Contents API 404）；
    ``manifest_failure`` 表示取清单这一步本身失败了。
    """

    def __init__(
        self,
        result: Repository,
        *,
        manifest: str | None = MANIFEST,
        failure: Exception | None = None,
        manifest_failure: Exception | None = None,
    ) -> None:
        self.result = result
        self.manifest_content = manifest
        self.failure = failure
        self.manifest_failure = manifest_failure
        self.calls: list[str] = []
        self.manifest_calls: list[tuple[str, str | None]] = []

    def repository(self, full_name: str) -> Repository:
        self.calls.append(full_name)
        if self.failure is not None:
            raise self.failure
        return self.result

    def manifest(self, full_name: str, *, ref: str | None = None) -> str | None:
        self.manifest_calls.append((full_name, ref))
        if self.manifest_failure is not None:
            raise self.manifest_failure
        return self.manifest_content

    def search(self, *_args: object, **_kwargs: object) -> object:
        raise AssertionError("install 不搜索")


def stub_cli(
    monkeypatch: pytest.MonkeyPatch,
    *,
    files: Mapping[str, str] | None = None,
    manifest: str | None = MANIFEST,
    result: Repository | None = None,
    failure: Exception | None = None,
    manifest_failure: Exception | None = None,
    verifier: MCPVerifier | None = None,
) -> tuple[FakeSource, FakeCloner]:
    """让 CLI 内部的 ``AppManager`` 用假 GitHub 与假 Git 装配。

    参数解析、``execute`` 的错误通道、退出码与渲染都走真实代码，只把两条对外出口
    换掉：CLI 的装配逻辑本身也是被测对象，所以这里不直接构造 manager 交给它。

    默认的克隆内容里带着清单文件：真实仓库若声明了 ``aurora-app.toml``，clone 下来
    的目录里当然有它，落在 staging 里的那一份必须和 API 读到的内容一致。

    ``verifier`` 默认是一个假工厂：安装默认就要连一次并发现工具，不给替身的话
    每条 CLI 用例都会真的去起一个子进程。要断言「连了什么」的用例自己传一个
    可检查的工厂进来。
    """
    source = FakeSource(
        result if result is not None else repository(),
        manifest=manifest,
        failure=failure,
        manifest_failure=manifest_failure,
    )
    cloner = FakeCloner(files if files is not None else {MANIFEST_NAME: MANIFEST})
    real = app_module.AppManager
    checker = MCPVerifier(FakeMcpClientFactory()) if verifier is None else verifier

    def build(store: AppStore, _source: GitHubSource) -> AppManager:
        # 真 source 换成 FakeSource：CLI 的装配仍然走真实代码，只有出口被换掉。
        return real(store, source, cloner=cloner, verifier=checker)  # type: ignore[arg-type]

    monkeypatch.setattr(app_module, "AppManager", build)
    return source, cloner


def candidate(
    command: tuple[str, ...] = WEATHER_COMMAND,
    *,
    repository_subdir: str = ".",
    evidence: str = MANIFEST_EVIDENCE,
    runtime: str = "python-uv",
) -> LaunchCandidate:
    """一份已确定的启动入口；字段全部可覆盖。"""
    return LaunchCandidate(
        command=command,
        runtime=runtime,
        evidence=evidence,
        repository_subdir=repository_subdir,
    )


def plan(
    *,
    package: str = WEATHER_PACKAGE,
    repository: str = "example/weather-mcp",
    ref: str = "main",
    commit: str = DEFAULT_COMMIT,
    install_path: str = WEATHER_PATH,
    repository_subdir: str = ".",
    working_dir: str | None = None,
    command: tuple[str, ...] = WEATHER_COMMAND,
    runtime: str = "python-uv",
    evidence: str = MANIFEST_EVIDENCE,
    enabled: bool = False,
    transport: str = "stdio",
) -> InstallPlan:
    """一份合格的安装计划；只给测试需要覆盖的字段传值。

    ``working_dir`` 默认跟随 ``install_path`` + ``repository_subdir``。这里不调用
    ``derive_working_dir``：builder 要是和生产逻辑共用实现，那条规则本身就没被
    任何测试验证过。
    """
    subdir = "" if repository_subdir == "." else f"/{repository_subdir}"
    return InstallPlan(
        repository=repository,
        ref=ref,
        commit=commit,
        package=package,
        install_path=install_path,
        repository_subdir=repository_subdir,
        working_dir=working_dir if working_dir is not None else f"{install_path}{subdir}",
        transport=transport,
        command=command,
        runtime=runtime,
        evidence=evidence,
        enabled=enabled,
    )


def staging(root: Path, files: Mapping[str, str] | None = None) -> Staging:
    """在 ``root`` 下造一份 staging 目录，并铺上预置文件。"""
    root.mkdir(parents=True, exist_ok=True)
    scratch = root.parent / f".aurora-scratch-{root.name}"
    scratch.mkdir(parents=True, exist_ok=True)
    for relative, content in (files or {}).items():
        path = root.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return Staging(root=root, scratch=scratch)


def agents_file(project_root: Path, ids: Sequence[str] = (DEFAULT_AGENT_ID,)) -> None:
    """给一个测试项目写一份最小的 ``config/agents.toml``。

    授权校验读的就是这个文件：它由 ``aurora setup`` 生成，所以测试要自己铺一份，
    而不是让被测代码去猜「没有 agents.toml 时有哪些 Agent」。
    """
    config = project_root / "config"
    config.mkdir(parents=True, exist_ok=True)
    body = "".join(f'[[agent]]\nid = "{item}"\n' for item in ids)
    config.joinpath("agents.toml").write_text(body, encoding="utf-8")


def write_origin(root: Path, url: str) -> None:
    """给一个目录写一份最小的 ``.git/config``，只含 origin。"""
    git = root / ".git"
    git.mkdir(parents=True, exist_ok=True)
    (git / "config").write_text(f'[remote "origin"]\n\turl = {url}\n', encoding="utf-8")


async def ignore_event(_event: McpInboundEvent) -> None:
    """一个什么都不做的事件处理器，供需要直接调 ``open`` 的测试使用。"""


__all__ = [
    "DEFAULT_AGENT_ID",
    "DEFAULT_COMMIT",
    "DEFAULT_PROTOCOL",
    "DEFAULT_TOOL_NAMES",
    "DEFAULT_TOOL_PREFIX",
    "ENDPOINT",
    "ENDPOINT_PACKAGE",
    "MANIFEST",
    "MANIFEST_EVIDENCE",
    "WEATHER_COMMAND",
    "WEATHER_PACKAGE",
    "WEATHER_PATH",
    "FakeMcpClientFactory",
    "FakeMcpPort",
    "FakeSource",
    "agents_file",
    "candidate",
    "ignore_event",
    "manifest_text",
    "plan",
    "staging",
    "stub_cli",
    "tools_page",
    "write_origin",
]
