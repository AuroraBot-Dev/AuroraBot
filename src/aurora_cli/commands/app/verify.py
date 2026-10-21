"""连接 MCP Server 并检查协议握手与工具目录。

诊断区分本地进程与远程端点，避免把远端连接问题表述成本机进程启动失败。
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from aurora_bot.mcp.client import SdkMcpClientFactory
from aurora_bot.mcp.models import McpAppSpec, McpEventMode, McpTransport
from aurora_bot.mcp.tool import bind_mcp_tool
from aurora_bot.utils.tasks import raise_with_cleanup, wait_for_completion
from aurora_cli.commands.app.install import DEFAULT_EVENT_MODE, DEFAULT_TIMEOUT_SECONDS
from aurora_cli.commands.app.models import ConfigError, VerifyError, is_secret_name

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

    from aurora_bot.mcp.client import McpClientFactory, McpClientPort
    from aurora_bot.mcp.events import McpInboundEvent
    from aurora_bot.mcp.tool import McpToolBinding

_TAIL_LINES = 4
_TAIL_CHARACTERS = 400
_REDACTED = "***"
_SUBJECTS = {
    McpTransport.STDIO: "本地 MCP Server",
    McpTransport.STREAMABLE_HTTP: "远程 MCP 端点",
}
_ENVIRONMENT_HINT = "检查所需环境变量（Server 可能需要计划中未声明的变量）"
_ENDPOINT_HINTS = (
    "确认该地址实现的是 MCP Streamable HTTP，而不是普通 REST 接口",
    "检查网络与证书：curl -i <url> 看得到 HTTP 状态吗",
)
_MAX_TOOL_PAGES = 1024
_MAX_TOOLS = 10_000


def verify_environment(names: Iterable[str] = ()) -> dict[str, str]:
    """从当前进程读取指定环境变量，作为本次 MCP 检查的额外环境。"""
    return {name: os.environ[name] for name in names if name in os.environ}


@dataclass(frozen=True, slots=True)
class Handshake:
    """连接参数与错误信息；``secrets`` 保存本次需脱敏的凭据值。"""

    label: str
    subject: str
    spec: McpAppSpec
    hints: tuple[str, ...]
    secrets: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class Inspection:
    """一次 MCP 连接检查的结论：协商版本 + 完整发现的工具目录。

    ``tools`` 为空是合法结论，不是失败：一个只推送世界事件、不对外暴露工具的
    Server 仍然是合法 MCP Server —— 它是**世界生产者**而不是工具提供者。
    """

    protocol_version: str
    tools: tuple[McpToolBinding, ...]

    @property
    def tool_ids(self) -> tuple[str, ...]:
        """已发现的领域工具 ID（``<package>:tool/definition/<raw_name>``）。"""
        return tuple(binding.definition.name for binding in self.tools)


def require_contribution(inspection: Inspection, handshake: Handshake, *, produces_events: bool) -> Inspection:
    """只登记**至少能贡献一种东西**的 Server。

    两种贡献：向 Bot 暴露 Tool（Act），或把外部事实推进世界线（世界生产者，
    ``event_mode = world_events``）。两者都做不到时，登记它没有任何意义 ——
    Bot 既调不动它，也等不到它。

    这里必须显式要求 ``produces_events``，而不是假定「零工具也无妨」：
    一个既没有 Tool、event_mode 又是 disabled 的条目纯粹是死配置。
    """
    if inspection.tools or produces_events:
        return inspection
    raise VerifyError(
        f"{handshake.label}（{handshake.subject}）连接成功，但没有发现任何可注册的 Tool。\n"
        "Aurora 只把 MCP 的 Tools 暴露给 Bot，所以这样的 Server 只有两种登记方式：\n"
        "  - 让它开放至少一个 Tool；\n"
        "  - 用 --events 声明它是世界生产者（只把外部事实推进 Bot 的世界线，不提供可调用的工具）。\n"
        "可尝试：确认该地址确实是 MCP Server，或检查 Server 是否需要启动参数来开放工具"
        "（例如允许访问的目录）"
    )


def install_hints(command: Sequence[str]) -> tuple[str, ...]:
    """安装期失败时建议检查环境和手动启动本地 Server。"""
    return (_ENVIRONMENT_HINT, f"手动运行：{' '.join(command)}")


def endpoint_hints(url: str, auth_env: str | None) -> tuple[str, ...]:
    """生成远程端点连接失败时的排查建议。"""
    hints = (f"{_ENDPOINT_HINTS[0]}：{url}", _ENDPOINT_HINTS[1])
    if auth_env is not None:
        hints = (*hints, f"检查环境变量 {auth_env}：它的值会作为 Bearer token 发出去")
    return hints


def process_target(
    label: str,
    command: Sequence[str],
    *,
    working_dir: Path,
    hints: tuple[str, ...],
    env_names: Iterable[str] = (),
) -> Handshake:
    """一个本地进程的连接说明。

    ``working_dir`` 由调用方决定：源码安装在 staging，包管理器安装在项目根目录。
    标准错误输出交由 SDK 客户端管理。
    """
    spec = McpAppSpec(
        package=label,
        enabled=False,
        transport=McpTransport.STDIO,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        terminal_logs=True,
        event_mode=McpEventMode(DEFAULT_EVENT_MODE),
        command=tuple(command),
        working_dir=working_dir,
        environment=verify_environment(env_names),
    )
    return Handshake(label=label, subject=_SUBJECTS[spec.transport], spec=spec, hints=hints, secrets=spec.environment)


def endpoint_target(
    label: str,
    url: str,
    *,
    hints: tuple[str, ...],
    auth_env: str | None = None,
) -> Handshake:
    """构造远程端点连接参数；声明了 auth_env 时要求该变量有值。"""
    token = None if auth_env is None else os.environ.get(auth_env)
    if auth_env is not None and not token:
        raise ConfigError(f"环境变量 {auth_env} 未设置或为空：{label} 用它的值做 Bearer token，请先设置后重试。")
    spec = McpAppSpec(
        package=label,
        enabled=False,
        transport=McpTransport.STREAMABLE_HTTP,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        terminal_logs=True,
        event_mode=McpEventMode(DEFAULT_EVENT_MODE),
        url=url,
        auth_token=token,
    )
    secrets = {} if auth_env is None or token is None else {auth_env: token}
    return Handshake(label=label, subject=_SUBJECTS[spec.transport], spec=spec, hints=hints, secrets=secrets)


def scrub_secrets(text: str, environment: Mapping[str, str], *, auth_token: str | None = None) -> str:
    """将显式认证凭据和敏感环境变量值替换为 ``***``。

    显式认证凭据始终脱敏；其余进程环境按变量名识别，保留工作目录等诊断信息。
    """
    if auth_token:
        text = text.replace(auth_token, _REDACTED)
    for name, value in environment.items():
        if value and is_secret_name(name):
            text = text.replace(value, _REDACTED)
    return text


async def _discover_bindings(package: str, port: McpClientPort) -> tuple[McpToolBinding, ...]:
    """完整读取 tools/list；用运行期同一个绑定函数校验工具定义。"""
    cursor: str | None = None
    visited: set[str] = set()
    raw_names: set[str] = set()
    bindings: list[McpToolBinding] = []
    page_count = 0
    while True:
        page_count += 1
        if page_count > _MAX_TOOL_PAGES:
            raise ValueError(f"MCP tools/list 页面过多：{package}")
        page = await port.list_tools(cursor=cursor)
        for remote in page.tools:
            if remote.name in raw_names:
                raise ValueError(f"MCP App 工具名称重复：{package}/{remote.name}")
            raw_names.add(remote.name)
            bindings.append(bind_mcp_tool(package, remote))
            if len(bindings) > _MAX_TOOLS:
                raise ValueError(f"MCP App 工具数量过多：{package}")
        cursor = page.next_cursor
        if cursor is None:
            return tuple(bindings)
        if cursor in visited:
            raise ValueError(f"MCP tools/list 返回了循环 cursor：{package}")
        visited.add(cursor)


class MCPVerifier:
    """连接 MCP 并发现工具；不修改 Aurora 注册表。"""

    def __init__(self, factory: McpClientFactory | None = None) -> None:
        """组装协作者；不传就用真实的 SDK 工厂，测试注入假实现。"""
        self._factory = SdkMcpClientFactory() if factory is None else factory

    def inspect(self, handshake: Handshake) -> Inspection:
        """同步执行一次连接检查，返回协议版本与工具目录。"""
        return asyncio.run(self.inspect_async(handshake))

    async def inspect_async(self, handshake: Handshake) -> Inspection:
        """检查完整工具目录后释放连接，失败或取消也必须等待释放结束。"""
        port = await self._connect(handshake)
        try:
            inspection = await self._inspect_connected(handshake, port)
        except BaseException as error:
            await self._disconnect(handshake, port, primary=error)
            raise
        await self._disconnect(handshake, port)
        return inspection

    async def _inspect_connected(self, handshake: Handshake, port: McpClientPort) -> Inspection:
        """将握手状态和发现失败转换为有阶段、已脱敏的验证错误。"""
        phase = "协议连接"
        try:
            if not port.connected:
                raise ValueError("握手完成后随即断开")
            version = port.protocol_version
            phase = "工具发现"
            tools = await _discover_bindings(handshake.spec.package, port)
        except Exception as error:
            reason = _tail(scrub_secrets(_error_detail(error), handshake.secrets, auth_token=handshake.spec.auth_token))
            raise VerifyError(_message(handshake, phase, reason)) from error
        return Inspection(protocol_version=version, tools=tools)

    async def _connect(self, handshake: Handshake) -> McpClientPort:
        """在配置的超时时间内打开 MCP 连接。"""
        spec = handshake.spec
        try:
            return await asyncio.wait_for(self._factory.open(spec, _ignore_event), timeout=spec.timeout_seconds)
        except TimeoutError as error:
            reason = f"超过 {spec.timeout_seconds:g} 秒仍未完成握手"
            raise VerifyError(_message(handshake, "协议连接", reason)) from error
        except Exception as error:
            reason = _tail(scrub_secrets(_error_detail(error), handshake.secrets, auth_token=handshake.spec.auth_token))
            raise VerifyError(_message(handshake, "启动进程或协议连接", reason)) from error

    async def _disconnect(
        self, handshake: Handshake, port: McpClientPort, *, primary: BaseException | None = None
    ) -> None:
        """完整等待关闭；公开诊断脱敏，原始错误与取消语义同时保留。"""
        outcomes, interrupted = await wait_for_completion(asyncio.gather(port.close(), return_exceptions=True))
        result = outcomes[0]
        failure: VerifyError | None = None
        if isinstance(result, BaseException):
            reason = _tail(
                scrub_secrets(_error_detail(result), handshake.secrets, auth_token=handshake.spec.auth_token)
            )
            failure = VerifyError(_message(handshake, "关闭", reason))
            failure.__cause__ = result
        failures = [failure] if failure is not None else []
        if interrupted is not None:
            raise_with_cleanup(primary if primary is not None else interrupted, failures, interrupted)
        if failure is not None:
            if primary is None:
                raise failure
            if isinstance(primary, Exception):
                raise VerifyError(f"{primary}\n\n{failure}") from ExceptionGroup(
                    "连接验证与资源释放同时失败", [primary, failure]
                )
            raise_with_cleanup(primary, failures)


async def _ignore_event(_event: McpInboundEvent) -> None:
    """握手检查不处理业务事件：event_mode 恒为 disabled，本来也收不到什么。"""


def _message(handshake: Handshake, phase: str, reason: str) -> str:
    """用目标、失败阶段和排查建议生成错误信息。"""
    hints = "".join(f"  - {hint}\n" for hint in handshake.hints)
    return f"{handshake.label}（{handshake.subject}）在{phase}阶段失败：{reason}\n\n可尝试：\n{hints}".rstrip("\n")


def _tail(text: str) -> str:
    """异常信息的有限长度尾巴；不把整份输出带进错误信息。"""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " ".join(lines[-_TAIL_LINES:])[:_TAIL_CHARACTERS]


def _error_detail(error: BaseException) -> str:
    """展开 SDK 的异常组，显示真正的连接错误。"""
    if isinstance(error, BaseExceptionGroup):
        return "; ".join(dict.fromkeys(_error_detail(item) for item in error.exceptions))
    return str(error) or type(error).__name__


__all__ = [
    "Handshake",
    "Inspection",
    "MCPVerifier",
    "endpoint_hints",
    "endpoint_target",
    "install_hints",
    "process_target",
    "require_contribution",
    "scrub_secrets",
    "verify_environment",
]
