"""RFC 0002 TOML configuration loading and validation."""

from __future__ import annotations

import copy
import hashlib
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigurationError(ValueError):
    """Raised before startup for invalid structural configuration."""


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError as error:
        raise ConfigurationError(f"configuration file does not exist: {path}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(f"invalid TOML in {path}: {error}") from error


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) != isinstance(value, dict):
            raise ConfigurationError(f"profile type mismatch at {key}")
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _require_keys(value: dict[str, Any], keys: set[str], label: str) -> None:
    unexpected = set(value) - keys
    missing = keys - set(value)
    if unexpected or missing:
        raise ConfigurationError(f"{label} has unexpected {sorted(unexpected)} or missing {sorted(missing)} keys")


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigurationError(f"{label} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    profile: str
    workspace: Path
    debug_host: str
    debug_port: int


@dataclass(frozen=True, slots=True)
class NodeConfig:
    id: str
    implementation: str
    inputs: frozenset[str]
    outputs: frozenset[str]
    capabilities: frozenset[str]
    model_roles: frozenset[str]


@dataclass(frozen=True, slots=True)
class AdapterConfig:
    id: str
    implementation: str
    capabilities: tuple["CapabilityConfig", ...]


@dataclass(frozen=True, slots=True)
class CapabilityConfig:
    """A Platform effect capability and its JSON Schema input contract."""

    id: str
    parameters_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ModelProviderConfig:
    """A TOML-defined LiteLLM or OpenAI-compatible Provider route."""

    id: str
    adapter: str
    secret_env: str
    base_url: str | None


@dataclass(frozen=True, slots=True)
class ModelRoleConfig:
    """Non-secret configuration for one model role."""

    provider: str
    model: str
    capabilities: frozenset[str]


@dataclass(frozen=True, slots=True)
class ModelLoggingConfig:
    """Opt-in DEBUG logging controls for the retained gateway implementation."""

    log_queries: bool
    log_responses: bool


@dataclass(frozen=True, slots=True)
class AuroraConfig:
    root: Path
    runtime: RuntimeConfig
    soul_path: Path
    soul_hash: str
    logging_level: str
    nodes: tuple[NodeConfig, ...]
    edges: dict[str, tuple[str, ...]]
    adapters: tuple[AdapterConfig, ...]
    model_roles: frozenset[str]
    model_definitions: dict[str, ModelRoleConfig]
    model_providers: dict[str, ModelProviderConfig]
    capability_definitions: dict[str, CapabilityConfig]
    model_logging: ModelLoggingConfig


def _parse_nodes(
    data: dict[str, Any], model_roles: frozenset[str]
) -> tuple[tuple[NodeConfig, ...], dict[str, tuple[str, ...]]]:
    _require_keys(data, {"node", "edge"}, "nodes.toml")
    raw_nodes = data["node"]
    raw_edges = data["edge"]
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise ConfigurationError("node and edge must be arrays")
    nodes: list[NodeConfig] = []
    ids: set[str] = set()
    for raw in raw_nodes:
        if not isinstance(raw, dict):
            raise ConfigurationError("node must be a table")
        _require_keys(
            raw,
            {"id", "enabled", "implementation", "inputs", "outputs", "capabilities", "model_roles"},
            "node",
        )
        if not isinstance(raw["enabled"], bool):
            raise ConfigurationError("node.enabled must be boolean")
        if not raw["enabled"]:
            continue
        node_id = _string(raw["id"], "node.id")
        if node_id in ids:
            raise ConfigurationError(f"duplicate node {node_id}")
        ids.add(node_id)
        fields = {name: raw[name] for name in ("inputs", "outputs", "capabilities", "model_roles")}
        list_fields_are_invalid = any(
            not isinstance(item, list) or not all(isinstance(item_value, str) for item_value in item)
            for item in fields.values()
        )
        if list_fields_are_invalid:
            raise ConfigurationError(f"node {node_id} list fields must contain strings")
        roles = frozenset(fields["model_roles"])
        if not roles <= model_roles:
            raise ConfigurationError(f"node {node_id} references unknown model roles")
        nodes.append(
            NodeConfig(
                id=node_id,
                implementation=_string(raw["implementation"], "node.implementation"),
                inputs=frozenset(fields["inputs"]),
                outputs=frozenset(fields["outputs"]),
                capabilities=frozenset(fields["capabilities"]),
                model_roles=roles,
            )
        )
    edges: dict[str, list[str]] = {}
    for raw in raw_edges:
        if not isinstance(raw, dict):
            raise ConfigurationError("edge must be a table")
        _require_keys(raw, {"event_type", "target"}, "edge")
        event_type = _string(raw["event_type"], "edge.event_type")
        target = _string(raw["target"], "edge.target")
        if target not in ids:
            raise ConfigurationError(f"edge references disabled or unknown node {target}")
        edges.setdefault(event_type, []).append(target)
    return tuple(nodes), {key: tuple(value) for key, value in edges.items()}


def _parse_adapters(data: dict[str, Any]) -> tuple[AdapterConfig, ...]:
    _require_keys(data, {"adapter"}, "apps.toml")
    raw_adapters = data["adapter"]
    if not isinstance(raw_adapters, list):
        raise ConfigurationError("adapter must be an array")
    adapters: list[AdapterConfig] = []
    ids: set[str] = set()
    for raw in raw_adapters:
        if not isinstance(raw, dict):
            raise ConfigurationError("adapter must be a table")
        _require_keys(raw, {"id", "enabled", "implementation", "capability"}, "adapter")
        if not isinstance(raw["enabled"], bool):
            raise ConfigurationError("adapter.enabled must be boolean")
        if not raw["enabled"]:
            continue
        adapter_id = _string(raw["id"], "adapter.id")
        if adapter_id in ids:
            raise ConfigurationError(f"duplicate adapter {adapter_id}")
        ids.add(adapter_id)
        capabilities = raw["capability"]
        if not isinstance(capabilities, list):
            raise ConfigurationError("adapter.capability must be an array")
        parsed_capabilities: list[CapabilityConfig] = []
        capability_ids: set[str] = set()
        for capability in capabilities:
            if not isinstance(capability, dict):
                raise ConfigurationError("adapter.capability must be a table")
            _require_keys(capability, {"id", "parameters_schema"}, "adapter.capability")
            capability_id = _string(capability["id"], "adapter.capability.id")
            schema = capability["parameters_schema"]
            if capability_id in capability_ids or not isinstance(schema, dict):
                raise ConfigurationError("adapter capability IDs must be unique and schemas must be tables")
            capability_ids.add(capability_id)
            parsed_capabilities.append(CapabilityConfig(capability_id, schema))
        adapters.append(
            AdapterConfig(
                adapter_id,
                _string(raw["implementation"], "adapter.implementation"),
                tuple(parsed_capabilities),
            )
        )
    return tuple(adapters)


def load_configuration(root: Path, profile: str | None = None) -> AuroraConfig:
    """Load the selected RFC 0002 configuration snapshot."""
    root = root.resolve()
    base = _read_toml(root / "config" / "aurora.toml")
    _require_keys(base, {"runtime", "soul", "logging", "storage", "models"}, "aurora.toml")
    runtime_raw = base["runtime"]
    if not isinstance(runtime_raw, dict):
        raise ConfigurationError("runtime must be a table")
    selected_profile = profile or os.environ.get("AURORA_PROFILE") or runtime_raw.get("profile")
    if not isinstance(selected_profile, str) or not selected_profile:
        raise ConfigurationError("no profile selected")
    merged = base
    profile_path = root / "config" / "profiles" / f"{selected_profile}.toml"
    if profile_path.exists():
        merged = _merge(base, _read_toml(profile_path))
    _require_keys(merged, {"runtime", "soul", "logging", "storage", "models"}, "merged aurora config")
    runtime_raw = merged["runtime"]
    soul_raw = merged["soul"]
    logging_raw = merged["logging"]
    storage_raw = merged["storage"]
    models_raw = merged["models"]
    if not all(isinstance(value, dict) for value in (runtime_raw, soul_raw, logging_raw, storage_raw, models_raw)):
        raise ConfigurationError("aurora top-level sections must be tables")
    _require_keys(runtime_raw, {"profile", "workspace", "debug_host", "debug_port"}, "runtime")
    _require_keys(soul_raw, {"path"}, "soul")
    _require_keys(logging_raw, {"level"}, "logging")
    _require_keys(storage_raw, {"data_dir"}, "storage")
    _require_keys(models_raw, {"roles", "providers", "logging"}, "models")
    debug_port = runtime_raw["debug_port"]
    if not isinstance(debug_port, int) or not 1 <= debug_port <= 65535:
        raise ConfigurationError("runtime.debug_port must be a valid port")
    debug_host = _string(runtime_raw["debug_host"], "runtime.debug_host")
    if selected_profile == "prod" and debug_host not in {"127.0.0.1", "::1", "localhost"}:
        raise ConfigurationError("production debug API must bind to loopback")
    roles = models_raw["roles"]
    providers = models_raw["providers"]
    model_logging = models_raw["logging"]
    if not isinstance(roles, dict) or not isinstance(providers, dict) or not isinstance(model_logging, dict):
        raise ConfigurationError("models.roles, models.providers and models.logging must be tables")
    _require_keys(model_logging, {"log_queries", "log_responses"}, "models.logging")
    if not isinstance(model_logging["log_queries"], bool) or not isinstance(model_logging["log_responses"], bool):
        raise ConfigurationError("models.logging values must be booleans")
    model_providers: dict[str, ModelProviderConfig] = {}
    for provider_id, settings in providers.items():
        if not isinstance(provider_id, str) or not isinstance(settings, dict):
            raise ConfigurationError("model provider IDs and settings must be tables")
        required_keys = {"adapter", "secret_env", "base_url"} if "base_url" in settings else {"adapter", "secret_env"}
        _require_keys(settings, required_keys, f"models.providers.{provider_id}")
        adapter = _string(settings["adapter"], f"models.providers.{provider_id}.adapter")
        if adapter not in {"litellm", "openai_compatible"}:
            raise ConfigurationError(f"models.providers.{provider_id}.adapter is unsupported")
        base_url = settings.get("base_url")
        if base_url is not None:
            base_url = _string(base_url, f"models.providers.{provider_id}.base_url")
        if adapter == "openai_compatible" and base_url is None:
            raise ConfigurationError(f"models.providers.{provider_id}.base_url is required")
        model_providers[provider_id] = ModelProviderConfig(
            id=provider_id,
            adapter=adapter,
            secret_env=_string(settings["secret_env"], f"models.providers.{provider_id}.secret_env"),
            base_url=base_url,
        )
    model_definitions: dict[str, ModelRoleConfig] = {}
    for role, settings in roles.items():
        if not isinstance(settings, dict):
            raise ConfigurationError(f"model role {role} must be a table")
        _require_keys(settings, {"provider", "model", "capabilities"}, f"models.roles.{role}")
        provider_id = _string(settings["provider"], f"models.roles.{role}.provider")
        if provider_id not in model_providers:
            raise ConfigurationError(f"models.roles.{role} references unknown provider")
        capabilities = settings["capabilities"]
        if not isinstance(capabilities, list) or not all(isinstance(value, str) for value in capabilities):
            raise ConfigurationError(f"models.roles.{role}.capabilities must contain strings")
        model_definitions[role] = ModelRoleConfig(
            provider=provider_id,
            model=_string(settings["model"], f"models.roles.{role}.model"),
            capabilities=frozenset(capabilities),
        )
    soul_path = (root / _string(soul_raw["path"], "soul.path")).resolve()
    try:
        soul_hash = hashlib.sha256(soul_path.read_bytes()).hexdigest()
    except FileNotFoundError as error:
        raise ConfigurationError(f"SOUL file does not exist: {soul_path}") from error
    nodes, edges = _parse_nodes(_read_toml(root / "config" / "nodes.toml"), frozenset(roles))
    adapters = _parse_adapters(_read_toml(root / "config" / "apps.toml"))
    capability_definitions: dict[str, CapabilityConfig] = {}
    for adapter in adapters:
        for capability in adapter.capabilities:
            if capability.id in capability_definitions:
                raise ConfigurationError(f"duplicate capability {capability.id}")
            capability_definitions[capability.id] = capability
    for node in nodes:
        if not node.capabilities <= capability_definitions.keys():
            raise ConfigurationError(f"node {node.id} requests unavailable capabilities")
    return AuroraConfig(
        root=root,
        runtime=RuntimeConfig(
            profile=selected_profile,
            workspace=(root / _string(runtime_raw["workspace"], "runtime.workspace")).resolve(),
            debug_host=debug_host,
            debug_port=debug_port,
        ),
        soul_path=soul_path,
        soul_hash=soul_hash,
        logging_level=_string(logging_raw["level"], "logging.level"),
        nodes=nodes,
        edges=edges,
        adapters=adapters,
        model_roles=frozenset(roles),
        model_definitions=model_definitions,
        model_providers=model_providers,
        capability_definitions=capability_definitions,
        model_logging=ModelLoggingConfig(
            log_queries=model_logging["log_queries"],
            log_responses=model_logging["log_responses"],
        ),
    )
