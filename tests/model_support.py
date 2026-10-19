"""离线模型共用真实端点值对象，只替换实际推理行为。"""

from src.contracts.model_binding import ModelBinding, ProviderDefinition, ai_resource_key
from src.contracts.resource import ResourceKey

_PROVIDER = ProviderDefinition(ResourceKey("test", "ai", "provider", "fake"), "fake", None, "AURORA_FAKE_MODEL_KEY")


def fake_endpoint(name: str) -> ModelBinding:
    """显式提供完整端点快照，不给不合法身份添加默认命名空间。"""
    key = ai_resource_key(name, "endpoint")
    return ModelBinding(key, _PROVIDER, key.path)


_NAMES = (
    "chat",
    "default",
    "embedding",
    "expected",
    "fake",
    "fast",
    "large-model",
    "model",
    "multimodal",
    "other",
    "quality",
    "quality-model",
    "root-model",
    "small-model",
    "tool-model",
    "worker-model",
)
_ENDPOINTS = {
    name: fake_endpoint(name)
    for name in (
        *(f"test:ai/endpoint/{name}" for name in _NAMES),
        *(f"aurora:ai/endpoint/{name}" for name in ("default", "fast", "quality", "multimodal", "embedding")),
    )
}


class FakeModelDirectory:
    """公开离线场景中声明的完整模型目录，所有配置快照均可被实际解析。"""

    @property
    def providers(self) -> tuple[ProviderDefinition, ...]:
        """测试模型不读取密钥，仍保留明确的提供方身份和引用语义。"""
        return (_PROVIDER,)

    @property
    def endpoints(self) -> tuple[ModelBinding, ...]:
        """返回稳定顺序的冻结端点，供正式装配归档。"""
        return tuple(_ENDPOINTS[name] for name in sorted(_ENDPOINTS))

    def resolve_endpoint(self, endpoint_id: str) -> ModelBinding:
        """未声明的端点明确失败，避免假模型掩盖错误引用。"""
        try:
            return _ENDPOINTS[endpoint_id]
        except KeyError as error:
            raise ValueError(f"未知 model endpoint：{endpoint_id}") from error
