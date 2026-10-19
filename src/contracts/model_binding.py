"""模型端点与提供方使用独立类别的原生资源身份。"""

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from src.contracts.resource import ResourceKey, ResourceRef
from src.contracts.resource_codec import resource_ref_data

PROVIDER_MEDIA_TYPE = "application/vnd.aurora.ai-provider+json;version=1"
MODEL_BINDING_MEDIA_TYPE = "application/vnd.aurora.ai-endpoint+json;version=1"
_ENVIRONMENT_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SDK_PROVIDER = re.compile(r"[A-Za-z0-9_-]+")


def ai_resource_key(name: str, kind: Literal["endpoint", "provider"]) -> ResourceKey:
    """端点选择与提供方绑定不能借用其他领域或类别的身份。"""
    try:
        key = ResourceKey.parse(name)
        if key.domain == "ai" and key.kind == kind:
            return key
    except ValueError as error:
        raise ValueError(f"模型资源身份必须形如 namespace:ai/{kind}/path：{name}") from error
    raise ValueError(f"模型资源身份必须形如 namespace:ai/{kind}/path：{name}")


@dataclass(frozen=True, slots=True)
class ProviderDefinition:
    """提供方的完整配置快照，密钥只保存环境变量引用。"""

    key: ResourceKey
    adapter: str
    base_url: str | None
    secret_env: str
    sdk_provider: str | None = None
    content: bytes = field(init=False, repr=False)
    ref: ResourceRef = field(init=False)

    def __post_init__(self) -> None:
        """密钥值不参与正文与版本，适配方式和实际地址保持明确。"""
        ai_resource_key(str(self.key), "provider")
        if not self.adapter.strip():
            raise ValueError("模型提供方必须声明适配方式")
        if _ENVIRONMENT_KEY.fullmatch(self.secret_env) is None:
            raise ValueError("模型密钥引用必须是合法环境变量名")
        route = self.sdk_provider
        if route is None and self.adapter in {"litellm", "openai_compatible"}:
            route = "openai" if self.adapter == "openai_compatible" else self.key.path
        if route is not None and (not isinstance(route, str) or _SDK_PROVIDER.fullmatch(route) is None):
            raise ValueError("sdk_provider 必须是非空协议前缀，不包含路径、冒号或空白")
        if self.adapter == "openai_compatible" and route != "openai":
            raise ValueError("OpenAI-compatible 适配必须使用 openai 作为 sdk_provider")
        object.__setattr__(self, "sdk_provider", route)
        content = _content(
            {
                "key": str(self.key),
                "adapter": self.adapter,
                "base_url": self.base_url,
                "secret_env": self.secret_env,
                "sdk_provider": route,
            }
        )
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "ref", ResourceRef(self.key, hashlib.sha256(content).hexdigest()))


@dataclass(frozen=True, slots=True)
class ModelBinding:
    """一次可选择的完整模型端点，提供方和调用策略都绑定确定版本。"""

    key: ResourceKey
    provider: ProviderDefinition
    model: str
    timeout_seconds: float = 30.0
    max_attempts: int = 2
    total_timeout_seconds: float = 60.0
    max_tokens: int | None = None
    content: bytes = field(init=False, repr=False)
    ref: ResourceRef = field(init=False)

    def __post_init__(self) -> None:
        """调用策略是实际执行依据，正文不能省略会影响请求和重试的字段。"""
        ai_resource_key(str(self.key), "endpoint")
        if not isinstance(self.provider, ProviderDefinition):
            raise TypeError("模型端点必须持有完整提供方快照")
        if not self.model.strip():
            raise ValueError("模型端点必须声明远端模型名称")
        for name in ("timeout_seconds", "total_timeout_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError("模型超时必须为有限正数")
            object.__setattr__(self, name, float(value))
        if self.total_timeout_seconds < self.timeout_seconds:
            raise ValueError("模型请求总超时不能小于单次尝试超时")
        if type(self.max_attempts) is not int or self.max_attempts <= 0:
            raise ValueError("模型请求最大尝试次数必须为正整数")
        if self.max_tokens is not None and (type(self.max_tokens) is not int or self.max_tokens <= 0):
            raise ValueError("模型输出预算必须为正整数")
        content = _content(
            {
                "key": str(self.key),
                "provider": resource_ref_data(self.provider.ref),
                "model": self.model,
                "timeout_seconds": self.timeout_seconds,
                "max_attempts": self.max_attempts,
                "total_timeout_seconds": self.total_timeout_seconds,
                "max_tokens": self.max_tokens,
            }
        )
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "ref", ResourceRef(self.key, hashlib.sha256(content).hexdigest()))


def _content(values: Mapping[str, object]) -> bytes:
    """同一组声明产生确定的 UTF-8 正文，显式保留协议版本。"""
    return json.dumps(
        {"schema_version": 1, **values}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
