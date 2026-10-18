"""命令与查询共用的版本化调用协议。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from src.contracts.data import freeze_object
from src.contracts.identity import Identifier
from src.contracts.kernel import ContributionKey
from src.contracts.resource import ResourceDescriptor, ResourceRef

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from src.contracts.world import ToolScopes


class OperationKind(StrEnum):
    """命令请求改变业务状态，查询只读取或计算结果。"""

    COMMAND = "command"
    QUERY = "query"


class OperationStatus(StrEnum):
    """实际执行的结果；未知状态需要调用者核对。"""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class OperationDefinition:
    """定义同时驱动资源发现、结构化调用与工具入口。"""

    ref: ResourceRef
    description: str
    parameters: Mapping[str, Any]
    tool_name: str | None = None
    retry_safe: bool = False

    def __post_init__(self) -> None:
        """固定参数结构并验证调用语义。"""
        if self.ref.revision is None:
            raise ValueError("操作定义必须声明确定版本")
        OperationKind(self.ref.key.kind)
        if not self.description.strip():
            raise ValueError("操作说明不能为空")
        if self.tool_name is not None and not Identifier.parse(self.tool_name).path.startswith("tool/"):
            raise ValueError("模型工具入口必须使用工具身份")
        object.__setattr__(self, "parameters", freeze_object(self.parameters))

    @property
    def kind(self) -> OperationKind:
        """操作种类由资源类别唯一决定。"""
        return OperationKind(self.ref.key.kind)

    @property
    def resource(self) -> ResourceDescriptor:
        """把能力定义投影为统一的资源发现条目。"""
        return ResourceDescriptor(
            self.ref,
            self.description,
            metadata={"parameters": self.parameters, "tool_name": self.tool_name, "retry_safe": self.retry_safe},
        )


@dataclass(frozen=True, slots=True)
class OperationRequest:
    """所有入口共用的调用身份、因果信息与参数。"""

    request_id: str
    bot_id: str
    source: str
    target: ResourceRef
    kind: OperationKind
    arguments: Mapping[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None
    caused_by: str | None = None
    deadline_at: datetime | None = None

    def __post_init__(self) -> None:
        """每次调用先固定可追溯身份和不可变内容。"""
        if not self.request_id.strip() or not self.source.strip():
            raise ValueError("操作请求需要非空请求身份和来源")
        if not Identifier.parse(self.bot_id).path.startswith("bot/"):
            raise ValueError("操作请求必须属于一个 Bot")
        if not isinstance(self.kind, OperationKind):
            raise TypeError("操作请求的种类必须是 OperationKind")
        for value in (self.correlation_id, self.caused_by):
            if value is not None and not value.strip():
                raise ValueError("关联身份和因果身份不能为空白文本")
        if self.deadline_at is not None and (self.deadline_at.tzinfo is None or self.deadline_at.utcoffset() is None):
            raise ValueError("操作期限必须包含时区")
        object.__setattr__(self, "arguments", freeze_object(self.arguments))

    @property
    def identity(self) -> str:
        """在主体和来源内稳定定位请求，字段边界不会因文本内容混淆。"""
        content = json.dumps((self.bot_id, self.source, self.request_id), ensure_ascii=False, separators=(",", ":"))
        return f"operation:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True, slots=True)
class OperationResult:
    """结构化执行结果，未知结果不能伪装为成功或安全失败。"""

    data: Mapping[str, Any] = field(default_factory=dict)
    status: OperationStatus = OperationStatus.SUCCEEDED
    message: str | None = None

    def __post_init__(self) -> None:
        """固定输出内容，失败与未知结果必须可解释。"""
        if not isinstance(self.status, OperationStatus):
            raise TypeError("操作结果状态必须是 OperationStatus")
        if self.status is not OperationStatus.SUCCEEDED and (self.message is None or not self.message.strip()):
            raise ValueError("失败或未知结果需要提供原因")
        object.__setattr__(self, "data", freeze_object(self.data))


class Operation(Protocol):
    """模组提供一个声明完整、可被路由的领域操作。"""

    @property
    def definition(self) -> OperationDefinition:
        """提供输入结构、版本与可选工具入口。"""
        ...

    def scopes_for(self, request: OperationRequest) -> ToolScopes:
        """在执行前声明需要读取和发布的世界域。"""
        ...

    async def execute(self, request: OperationRequest) -> OperationResult:
        """执行一次调用，幂等操作使用请求身份保护业务状态。"""
        ...


OPERATION_CONTRIBUTIONS = ContributionKey[Operation]("aurora:operations/contribution/handlers")
