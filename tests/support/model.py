"""离线模型共用真实端点值对象，只替换实际推理行为。"""

from dataclasses import dataclass, field

from aurora_bot.contracts import ChatMessage, ModelRequest
from aurora_bot.contracts.model_binding import ModelBinding, ProviderDefinition, ai_resource_key
from aurora_bot.contracts.resource import ResourceKey

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


_TEMPLATE_ENDPOINTS = frozenset(
    f"aurora:ai/endpoint/{name}" for name in ("default", "fast", "quality", "multimodal", "embedding")
)


@dataclass(slots=True)
class TemplateModel(FakeModelDirectory):
    """组合测试使用配置模板中的端点，记录请求并返回固定回复。"""

    requests: list[ModelRequest] = field(default_factory=list)

    @property
    def endpoints(self) -> tuple[ModelBinding, ...]:
        return tuple(FakeModelDirectory.resolve_endpoint(self, name) for name in sorted(_TEMPLATE_ENDPOINTS))

    def resolve_endpoint(self, endpoint_id: str) -> ModelBinding:
        if endpoint_id not in _TEMPLATE_ENDPOINTS:
            raise ValueError(f"未知 model endpoint：{endpoint_id}")
        return FakeModelDirectory.resolve_endpoint(self, endpoint_id)

    async def complete(self, request: ModelRequest) -> ChatMessage:
        self.requests.append(request)
        return ChatMessage.assistant("done")


@dataclass(slots=True)
class ScriptedModel(FakeModelDirectory):
    """认知循环测试逐次消费明确给定的回复，并保留实际请求。"""

    responses: list[ChatMessage]
    requests: list[ModelRequest] = field(default_factory=list)

    async def complete(self, request: ModelRequest) -> ChatMessage:
        self.requests.append(request)
        return self.responses.pop(0)
