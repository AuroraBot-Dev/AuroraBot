"""模型资源持有客户端，消费者借用启动前后身份不变的资源对象。"""

from aurora_core import Id, plug

from .content import require_capabilities
from .contract import ChatCapabilities, ModelConfig
from .plugins.model._meta import (
    CHAT_CLEAN,
    CHAT_PREPARE,
    CHOICE_CLEAN,
    CHOICE_PREPARE,
    EMBEDDING_CLEAN,
    EMBEDDING_PREPARE,
)


class ModelResource:
    def __init__(self, ctx, registry, resolve_credential, *, states, options):
        self.ctx, self.registry, self.resolve_credential = ctx, registry, resolve_credential
        self.states, self.options = states, options
        self.client = None
        self.catalog = None

    def bind(self, *, catalog=None):
        self.catalog = catalog

    async def _prepare(self):
        values = self.options
        if "profiles" in self.states:
            binding = self.states["profiles"]
            values = self.ctx.get(binding.key, location=dict(binding.location))[values["profile"]]
        adapter = self.registry.get(Id(values["adapter"])).target
        if adapter.kind != self.kind:
            raise TypeError(f"模型资源需要 {self.kind} 适配器")
        config = {key: value for key, value in values.items() if key not in ("adapter", "credential")}
        if "capabilities" in config:
            config["capabilities"] = ChatCapabilities(**config["capabilities"])
        credential = values.get("credential")
        api_key = None if credential is None else self.resolve_credential(credential)
        self.client = await adapter.factory(ModelConfig(**config), api_key=api_key)
        if self.kind == "chat" and self.catalog is not None:
            require_capabilities(self.client, {"messages": [], "tools": self.catalog.definitions()}, streaming=False)

    async def aclose(self):
        if self.client is not None:
            await self.client.aclose()
            self.client = None


class ChatResource(ModelResource):
    kind = "chat"

    @plug(CHAT_PREPARE)
    async def prepare(self):
        await self._prepare()

    @plug(CHAT_CLEAN)
    async def clean(self):
        await self.aclose()

    @property
    def capabilities(self):
        return self.client.capabilities

    async def complete(self, request):
        return await self.client.complete(request)

    def stream(self, request):
        return self.client.stream(request)


class ChoiceResource(ModelResource):
    kind = "choice"

    @plug(CHOICE_PREPARE)
    async def prepare(self):
        await self._prepare()

    @plug(CHOICE_CLEAN)
    async def clean(self):
        await self.aclose()

    async def choose(self, request):
        return await self.client.choose(request)


class EmbeddingResource(ModelResource):
    kind = "embedding"

    @plug(EMBEDDING_PREPARE)
    async def prepare(self):
        await self._prepare()

    @plug(EMBEDDING_CLEAN)
    async def clean(self):
        await self.aclose()

    async def embed(self, texts):
        return await self.client.embed(texts)
