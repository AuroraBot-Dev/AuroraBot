from __future__ import annotations

from typing import TYPE_CHECKING

from aurora import load_config
from aurora.config import assemble_config
from aurora.configuration.endpoints import ENDPOINTS_CONFIG, EndpointConfig
from aurora.configuration.providers import PROVIDERS_CONFIG, ProviderConfig

if TYPE_CHECKING:
    from pathlib import Path

_PROVIDERS = """\
[[provider]]
name = "deepseek"
adapter = "litellm"
secret_env = "DEEPSEEK_API_KEY"

[[provider]]
name = "siliconflow"
adapter = "openai_compatible"
base_url = "https://api.siliconflow.cn/v1"
secret_env = "SILICONFLOW_API_KEY"
"""

_ENDPOINTS = """\
[[endpoint]]
name = "default"
provider = "deepseek"
model = "deepseek-chat"
"""


def _load_providers(tmp_path: Path, content: str) -> tuple[ProviderConfig, ...]:
    config_directory = tmp_path / "config"
    config_directory.mkdir(exist_ok=True)
    (config_directory / "providers.toml").write_text(content, encoding="utf-8")
    return assemble_config(tmp_path, (PROVIDERS_CONFIG,)).get(PROVIDERS_CONFIG)


def _load_endpoints(tmp_path: Path, content: str) -> tuple[EndpointConfig, ...]:
    config_directory = tmp_path / "config"
    config_directory.mkdir(exist_ok=True)
    (config_directory / "endpoints.toml").write_text(content, encoding="utf-8")
    return assemble_config(tmp_path, (ENDPOINTS_CONFIG,)).get(ENDPOINTS_CONFIG)


def test_template_exports_typed_provider_and_endpoint_configuration(configured_project: Path) -> None:
    configuration = load_config(configured_project)
    providers = configuration.get(PROVIDERS_CONFIG)
    endpoints = configuration.get(ENDPOINTS_CONFIG)

    assert providers[0] == ProviderConfig("deepseek", "litellm", "DEEPSEEK_API_KEY")
    assert providers[3] == ProviderConfig(
        "siliconflow", "openai_compatible", "SILICONFLOW_API_KEY", base_url="https://api.siliconflow.cn/v1"
    )
    assert endpoints[0] == EndpointConfig("default", "deepseek", "deepseek-chat")
    assert endpoints[1].name == "fast"
    assert endpoints[2].model == "deepseek-v4-pro"


def test_providers_parses_exact_values(tmp_path: Path) -> None:
    providers = _load_providers(tmp_path, _PROVIDERS)

    assert providers[0].adapter == "litellm"
    assert providers[1].base_url == "https://api.siliconflow.cn/v1"


def test_endpoints_parses_exact_values(tmp_path: Path) -> None:
    endpoints = _load_endpoints(tmp_path, _ENDPOINTS)

    assert endpoints[0].provider == "deepseek"
    assert endpoints[0].model == "deepseek-chat"
