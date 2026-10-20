from __future__ import annotations

from typing import TYPE_CHECKING

from aurora import load_config
from aurora.configs.endpoints import CONFIG_SPEC as ENDPOINTS_CONFIG
from aurora.configs.providers import CONFIG_SPEC as PROVIDERS_CONFIG
from aurora.configurator import assemble_config
from aurorabot.ai.config import EndpointConfig, ProviderConfig

if TYPE_CHECKING:
    from pathlib import Path

_PROVIDERS = """\
[[provider]]
name = "aurora:ai/provider/deepseek"
adapter = "litellm"
secret_env = "DEEPSEEK_API_KEY"

[[provider]]
name = "aurora:ai/provider/siliconflow"
adapter = "openai_compatible"
base_url = "https://api.siliconflow.cn/v1"
secret_env = "SILICONFLOW_API_KEY"
"""

_ENDPOINTS = """\
[[endpoint]]
name = "aurora:ai/endpoint/default"
provider = "aurora:ai/provider/deepseek"
model = "deepseek-chat"
"""


def _load_providers(tmp_path: Path, content: str) -> tuple[ProviderConfig, ...]:
    config_directory = tmp_path / "config"
    config_directory.mkdir(exist_ok=True)
    (config_directory / "providers.toml").write_text(content, encoding="utf-8")
    return assemble_config(tmp_path, (PROVIDERS_CONFIG,)).get(PROVIDERS_CONFIG).providers


def _load_endpoints(tmp_path: Path, content: str) -> tuple[EndpointConfig, ...]:
    config_directory = tmp_path / "config"
    config_directory.mkdir(exist_ok=True)
    (config_directory / "endpoints.toml").write_text(content, encoding="utf-8")
    return assemble_config(tmp_path, (ENDPOINTS_CONFIG,)).get(ENDPOINTS_CONFIG).endpoints


def test_template_exports_typed_provider_and_endpoint_config(configured_project: Path) -> None:
    config = load_config(configured_project)
    providers = config.get(PROVIDERS_CONFIG).providers
    endpoints = config.get(ENDPOINTS_CONFIG).endpoints

    assert providers[0] == ProviderConfig(
        "aurora:ai/provider/deepseek", "litellm", "DEEPSEEK_API_KEY", sdk_provider="deepseek"
    )
    assert providers[3] == ProviderConfig(
        "aurora:ai/provider/siliconflow",
        "openai_compatible",
        "SILICONFLOW_API_KEY",
        base_url="https://api.siliconflow.cn/v1",
        sdk_provider="openai",
    )
    assert endpoints[0] == EndpointConfig("aurora:ai/endpoint/default", "aurora:ai/provider/deepseek", "deepseek-chat")
    assert endpoints[1].name == "aurora:ai/endpoint/fast"
    assert endpoints[2].model == "deepseek-v4-pro"


def test_providers_parses_exact_values(tmp_path: Path) -> None:
    providers = _load_providers(tmp_path, _PROVIDERS)

    assert providers[0].adapter == "litellm"
    assert providers[1].base_url == "https://api.siliconflow.cn/v1"


def test_endpoints_parses_exact_values(tmp_path: Path) -> None:
    endpoints = _load_endpoints(tmp_path, _ENDPOINTS)

    assert endpoints[0].provider == "aurora:ai/provider/deepseek"
    assert endpoints[0].model == "deepseek-chat"
