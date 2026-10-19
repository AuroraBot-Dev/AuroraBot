"""命名空间、领域和资源类别组成的统一寻址契约。"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.contracts.data import freeze_object
from src.contracts.identity import Identifier, is_namespace, is_path
from src.contracts.kernel import ContributionKey

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


@dataclass(frozen=True, slots=True, order=True)
class ResourceKey:
    """资源定义的稳定身份，版本与运行实例单独记录。"""

    namespace: str
    domain: str
    kind: str
    path: str

    def __post_init__(self) -> None:
        """验证每个寻址维度，避免业务代码自行切分字符串。"""
        for label, value in (("命名空间", self.namespace), ("领域", self.domain), ("类别", self.kind)):
            if not is_namespace(value):
                raise ValueError(f"资源{label}无效：{value!r}")
        if not is_path(self.path):
            raise ValueError(f"资源路径无效：{self.path!r}")

    @classmethod
    def parse(cls, text: str) -> ResourceKey:
        """解析 namespace:domain/kind/path 形式的资源身份。"""
        identifier = Identifier.parse(text)
        parts = identifier.path.split("/", maxsplit=2)
        try:
            domain, kind, path = parts
        except ValueError as error:
            raise ValueError("资源身份必须形如 namespace:domain/kind/path") from error
        return cls(identifier.namespace, domain, kind, path)

    def __str__(self) -> str:
        """返回规范的可序列化资源身份。"""
        return f"{self.namespace}:{self.domain}/{self.kind}/{self.path}"


@dataclass(frozen=True, slots=True)
class ResourceRef:
    """对一个资源版本或待解析别名的引用。"""

    key: ResourceKey
    revision: str | None = None

    def __post_init__(self) -> None:
        """版本一旦给出就必须是明确且非空的值。"""
        if self.revision is not None and (not self.revision.strip() or self.revision != self.revision.strip()):
            raise ValueError("资源版本必须是非空且无首尾空白的文本")


def fixed_resource_refs(values: Iterable[ResourceRef]) -> tuple[ResourceRef, ...]:
    """固定调用方实际使用的资源顺序，拒绝未解析版本和重复来源。"""
    refs = tuple(values)
    if any(not isinstance(ref, ResourceRef) or ref.revision is None for ref in refs):
        raise ValueError("输入资源必须引用明确版本")
    if len(refs) != len(set(refs)):
        raise ValueError("输入资源引用不能重复")
    return refs


@dataclass(frozen=True, slots=True)
class ResourceDescriptor:
    """可发现的资源定义，内容可以由所属模组单独存储。"""

    ref: ResourceRef
    description: str
    contract: ResourceRef | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """固定元数据，定义必须绑定确定版本。"""
        if self.ref.revision is None:
            raise ValueError("资源定义必须声明确定版本")
        if not self.description.strip():
            raise ValueError("资源说明不能为空")
        if self.contract is not None and self.contract.revision is None:
            raise ValueError("能力契约必须声明确定版本")
        object.__setattr__(self, "metadata", freeze_object(self.metadata))


@dataclass(frozen=True, slots=True)
class ResourceAlias:
    """显式把一个资源名称绑定到另一个确定版本。"""

    key: ResourceKey
    target: ResourceRef

    def __post_init__(self) -> None:
        """别名保持领域和类别，防止跨语义替换。"""
        if (self.key.domain, self.key.kind) != (self.target.key.domain, self.target.key.kind):
            raise ValueError("资源别名必须保持领域和类别")
        if self.target.revision is None:
            raise ValueError("资源别名必须指向确定版本")


@dataclass(frozen=True, slots=True)
class ResourceInstance:
    """属于某个 Bot 的资源运行实例，引用冻结的定义版本。"""

    instance_id: str
    bot_id: str
    definition: ResourceRef

    def __post_init__(self) -> None:
        """验证实例身份与确定的恢复依据。"""
        if not self.instance_id.strip():
            raise ValueError("资源实例身份不能为空")
        identifier = Identifier.parse(self.bot_id)
        if not identifier.path.startswith("bot/"):
            raise ValueError("资源实例必须属于一个 Bot 身份")
        if self.definition.revision is None:
            raise ValueError("资源实例必须引用确定的定义版本")

    @property
    def key(self) -> ResourceKey:
        """以 Bot 和原始实例身份寻址，定义版本变化不改变实例名称。"""
        definition = self.definition.key
        return ResourceKey(
            definition.namespace, definition.domain, "instance", _instance_path(self.bot_id, self.instance_id)
        )


def resource_instance_identity(key: ResourceKey) -> tuple[str, str]:
    """从规范实例地址还原 Bot 与原始实例 ID，拒绝多义或损坏编码。"""
    try:
        if key.kind != "instance" or not key.path.startswith("v1_"):
            raise ValueError("实例地址类别或编码版本无效")
        token = key.path[3:]
        raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
        identity = json.loads(raw)
        if not isinstance(identity, list):
            raise ValueError("实例地址必须包含 Bot 和实例身份")
        bot_id, instance_id = identity
        if not isinstance(bot_id, str) or not isinstance(instance_id, str) or not instance_id.strip():
            raise ValueError("实例地址身份必须是非空文本")
        if not Identifier.parse(bot_id).path.startswith("bot/") or key.path != _instance_path(bot_id, instance_id):
            raise ValueError("实例地址不是规范编码")
        return bot_id, instance_id
    except (ValueError, TypeError, UnicodeError, binascii.Error) as error:
        raise ValueError("资源实例地址无效") from error


def _instance_path(bot_id: str, instance_id: str) -> str:
    """原始身份用无损 UTF-8 编码进入资源路径，不改写 Bot 或运行 ID。"""
    raw = json.dumps([bot_id, instance_id], ensure_ascii=False, separators=(",", ":")).encode()
    return "v1_" + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


RESOURCE_CONTRIBUTIONS = ContributionKey[ResourceDescriptor]("aurora:resources/contribution/definitions")
RESOURCE_ALIASES = ContributionKey[ResourceAlias]("aurora:resources/contribution/aliases")
