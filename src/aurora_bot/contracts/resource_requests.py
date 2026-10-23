"""资源发现与检查操作的公共参数和确定身份。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from aurora_bot.contracts.resource import ResourceKey, ResourceRef
from aurora_bot.contracts.resource_query import MAX_RESOURCE_CURSOR_LENGTH, MAX_RESOURCE_PAGE, ResourceQuery

RESOURCE_FIND = ResourceRef(ResourceKey("aurora", "resources", "query", "find"), "1")
RESOURCE_INSPECT = ResourceRef(ResourceKey("aurora", "resources", "query", "inspect"), "1")


class ResourceQueryInput(BaseModel):
    """有界发现按命名空间、领域和类别筛选，续页保持筛选不变。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    namespace: str | None = None
    domain: str | None = None
    kind: str | None = None
    limit: int = Field(default=20, ge=1, le=MAX_RESOURCE_PAGE)
    after: str | None = Field(default=None, min_length=1, max_length=MAX_RESOURCE_CURSOR_LENGTH)

    @property
    def query(self) -> ResourceQuery:
        """结构与语义共同校验后交给提供者。"""
        return ResourceQuery(self.namespace, self.domain, self.kind, self.limit, self.after)


class ResourceInspectInput(BaseModel):
    """静态定义可以使用别名，动态内容必须由调用方给出版本。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    resource: str
    revision: str | None = None
    contract: str | None = None
    contract_revision: str | None = None

    @property
    def ref(self) -> ResourceRef:
        """将结构化请求转为统一资源引用。"""
        return ResourceRef(ResourceKey.parse(self.resource), self.revision)

    @property
    def required_contract(self) -> ResourceRef | None:
        """请求能力匹配时，契约名称与版本必须同时明确。"""
        if self.contract is None and self.contract_revision is None:
            return None
        if self.contract is None or self.contract_revision is None:
            raise ValueError("能力契约必须同时给出名称与版本")
        return ResourceRef(ResourceKey.parse(self.contract), self.contract_revision)
