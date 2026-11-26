"""模型 profile 配置与角色引用；运行时工厂和凭证不进入 ctx。"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict, cast, overload

from aurora_config import ConfigSchema
from aurora_core.ids import Id
from aurora_core.registry import DefinitionRegistry

from .contract import (
    ChatCapabilities,
    ChatClient,
    ChoiceClient,
    EmbeddingClient,
    ModelConfig,
    ModelFactory,
    ModelKind,
    ThinkingConfig,
)

ADAPTERS = Id("org.aurora.adapter:registries/model/adapters")
CONFIG = Id("org.aurora.adapter:state/model/config")
BINDINGS = Id("org.aurora.adapter:state/model/bindings")


class ModelProfile(TypedDict):
    """credential 为运行期凭证引用名称，不允许保存 api_key。"""

    adapter: str
    model: str
    base_url: NotRequired[str]
    credential: NotRequired[str]
    provider: NotRequired[str]
    capabilities: NotRequired[dict[str, bool]]
    thinking: NotRequired[ThinkingConfig]
    reasoning_effort: NotRequired[str]


_TEXT = {"type": "string", "pattern": r"\S"}
PROFILE_SCHEMA = ConfigSchema(
    {
        "type": "object",
        "propertyNames": {"minLength": 1},
        "additionalProperties": {
            "type": "object",
            "required": ["adapter", "model"],
            "additionalProperties": False,
            "properties": {
                "adapter": {"type": "string", "format": "aurora-id"},
                "model": _TEXT,
                "base_url": _TEXT,
                "credential": _TEXT,
                "provider": _TEXT,
                "thinking": {
                    "type": "object",
                    "required": ["type"],
                    "additionalProperties": False,
                    "properties": {
                        "type": {"enum": ["enabled", "disabled"]},
                        "budget_tokens": {"type": "integer", "minimum": 1024},
                    },
                },
                "reasoning_effort": {"enum": ["none", "minimal", "low", "medium", "high", "xhigh", "max"]},
                "capabilities": {
                    "type": "object",
                    "required": ["streaming", "tool_calls"],
                    "additionalProperties": False,
                    "properties": {
                        "streaming": {"type": "boolean"},
                        "tool_calls": {"type": "boolean"},
                        "file_input": {"type": "boolean"},
                    },
                },
            },
        },
    }
)
BINDINGS_SCHEMA = ConfigSchema(
    {
        "type": "object",
        "propertyNames": {"minLength": 1},
        "additionalProperties": {"type": "string", "minLength": 1},
    }
)


def check_bindings(values: Mapping[Id, object]) -> None:
    profiles = cast(dict, values[CONFIG])
    bindings = cast(dict, values[BINDINGS])
    if any(name not in profiles for name in bindings.values()):
        raise ValueError("模型绑定引用了不存在的配置")


@dataclass(frozen=True)
class ModelAdapter[T]:
    """同一注册表中的类型化工厂，防止聊天、决策与向量角色混用。"""

    kind: ModelKind
    factory: ModelFactory[T]


@dataclass(frozen=True)
class ResolvedModel[T]:
    """已解析的实例工厂、公开配置和运行期凭证引用。"""

    profile_name: str
    factory: ModelFactory[T]
    config: ModelConfig
    credential: str | None
    adapter: str


@overload
def resolve_model(
    registry: DefinitionRegistry, profiles: object, bindings: object, role: str, *, kind: Literal["chat"] = "chat"
) -> ResolvedModel[ChatClient]: ...


@overload
def resolve_model(
    registry: DefinitionRegistry, profiles: object, bindings: object, role: str, *, kind: Literal["choice"]
) -> ResolvedModel[ChoiceClient]: ...


@overload
def resolve_model(
    registry: DefinitionRegistry, profiles: object, bindings: object, role: str, *, kind: Literal["embedding"]
) -> ResolvedModel[EmbeddingClient]: ...


def resolve_model(
    registry: DefinitionRegistry, profiles: object, bindings: object, role: str, *, kind: ModelKind = "chat"
) -> ResolvedModel:
    """只解析已登记的匹配工厂；不导入用户模块、不创建客户端。"""
    name, profile, config = _profile(profiles, bindings, role)
    entry = registry.get(Id(profile["adapter"]))
    if entry.kind != "adapter" or entry.register_to != ADAPTERS or not isinstance(entry.target, ModelAdapter):
        raise TypeError("模型配置目标必须为 adapters 注册表中的 ModelAdapter 工厂")
    if entry.target.kind != kind:
        raise TypeError(f"模型角色需要 {kind} 适配器，不能使用 {entry.target.kind}")
    if kind != "chat" and (
        config.capabilities is not None or config.thinking is not None or config.reasoning_effort is not None
    ):
        raise ValueError("非聊天模型不接受聊天能力或思考配置")
    return ResolvedModel(name, entry.target.factory, config, profile.get("credential"), str(entry.id))


def _profile(profiles: object, bindings: object, role: str) -> tuple[str, ModelProfile, ModelConfig]:
    PROFILE_SCHEMA.validate(profiles)
    BINDINGS_SCHEMA.validate(bindings)
    profiles = cast(dict[str, ModelProfile], profiles)
    bindings = cast(dict[str, str], bindings)
    if role not in bindings:
        raise ValueError(f"模型角色未绑定：{role}")
    if any(name not in profiles for name in bindings.values()):
        raise ValueError("模型绑定引用了不存在的配置")
    name = bindings[role]
    profile = profiles[name]
    capabilities = profile.get("capabilities")
    return (
        name,
        profile,
        ModelConfig(
            profile["model"],
            profile.get("base_url"),
            provider=profile.get("provider"),
            capabilities=None if capabilities is None else ChatCapabilities(**capabilities),
            thinking=profile.get("thinking"),
            reasoning_effort=cast(Any, profile.get("reasoning_effort")),
        ),
    )
