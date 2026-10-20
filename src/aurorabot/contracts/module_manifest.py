"""模组发布版本与内核公开 API 的兼容声明。"""

from dataclasses import dataclass

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from aurorabot.contracts.identity import is_namespace
from aurorabot.contracts.resource import ResourceKey, ResourceRef

MODULE_MANIFEST_MEDIA_TYPE = "application/vnd.aurora.module-manifest+json;version=1"
MODULE_MANIFEST_CONTRACT = ResourceRef(ResourceKey("aurora", "kernel", "contract", "module"), "1")


@dataclass(frozen=True, slots=True)
class ModuleManifest:
    """发布版本不决定兼容性；兼容范围由模组针对内核 API 单独声明。"""

    version: str = "1.0.0"
    kernel_api: str = ">=1,<2"
    namespace: str = "aurora"

    def __post_init__(self) -> None:
        """使用标准发布版本和范围语法，拒绝空白与格式无效的声明。"""
        if not isinstance(self.namespace, str) or not is_namespace(self.namespace):
            raise ValueError("模组必须声明合法命名空间")
        for value in (self.version, self.kernel_api):
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError("模组版本与内核 API 范围必须是非空且无首尾空白的文本")
        try:
            version = Version(self.version)
            api = SpecifierSet(self.kernel_api)
        except (InvalidVersion, InvalidSpecifier) as error:
            raise ValueError("模组发布版本或内核 API 范围无效") from error
        object.__setattr__(self, "version", str(version))
        object.__setattr__(self, "kernel_api", str(api))

    def accepts(self, api_version: str) -> bool:
        """按标准范围比较 API 版本，不借模组自己的发布版本推断兼容性。"""
        return Version(api_version) in SpecifierSet(self.kernel_api)


DEFAULT_MODULE_MANIFEST = ModuleManifest()
