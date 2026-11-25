"""定义总表及其分类视图。"""

from collections.abc import Iterable
from dataclasses import dataclass

from .ids import Id


@dataclass(frozen=True)
class RegistryEntry:
    """公开定义及接收关系；target 保留原始对象，不强制可调用。"""

    id: Id
    kind: str
    target: object
    provider: str
    register_to: Id | None = None
    slot: Id | None = None
    interface: object | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, Id):
            raise TypeError("登记项 id 必须为 Id")
        if not self.kind or not self.provider:
            raise ValueError("登记项必须声明 kind 与提供者")
        for relation in (self.register_to, self.slot):
            if relation is not None and not isinstance(relation, Id):
                raise TypeError("登记关系必须为 Id")


class DefinitionRegistry:
    """同一作用域内的唯一总表；修改必须通过显式登记或替换。"""

    def __init__(self) -> None:
        self._definitions: dict[Id, RegistryEntry] = {}

    def register(self, entry: RegistryEntry) -> None:
        self.register_many((entry,))

    def register_many(self, entries: Iterable[RegistryEntry]) -> None:
        """整批检查身份冲突，通过后一次性加入，失败时保持总表不变。"""
        pending: dict[Id, RegistryEntry] = {}
        for entry in entries:
            if entry.id in self._definitions or entry.id in pending:
                raise ValueError(f"重复的公共 ID：{entry.id}，提供者：{entry.provider}")
            pending[entry.id] = entry
        self._definitions.update(pending)

    def replace(self, entry: RegistryEntry) -> None:
        """显式替换既有定义；不存在的目标必须使用登记接口。"""
        if entry.id not in self._definitions:
            raise KeyError(f"替换目标不存在：{entry.id}")
        self._definitions[entry.id] = entry

    def get(self, identity: Id) -> RegistryEntry:
        return self._definitions[identity]

    def entries(self) -> tuple[RegistryEntry, ...]:
        return tuple(self._definitions.values())

    def view(self, *, kind: str | None = None, register_to: Id | None = None) -> tuple[RegistryEntry, ...]:
        """从总表读取分类视图，不建立第二份对象存储。"""
        return tuple(
            entry
            for entry in self._definitions.values()
            if (kind is None or entry.kind == kind) and (register_to is None or entry.register_to == register_to)
        )

    def resolve(self, name: str, *, namespace: str, domain: str) -> RegistryEntry:
        """在显式上下文中解析路径或末段短名，拒绝歧义。"""
        if ":" in name:
            return self.get(Id(name))
        context = Id(f"{namespace}:{domain}/{name}")
        matches = [
            entry
            for entry in self._definitions.values()
            if entry.id.namespace == context.namespace
            and entry.id.domain == context.domain
            and (entry.id.local_path == name or entry.id.local_path.endswith(f"/{name}"))
        ]
        if not matches:
            raise KeyError(f"未找到定义：{context}")
        if len(matches) != 1:
            raise ValueError(f"短名存在歧义：{name}")
        return matches[0]
