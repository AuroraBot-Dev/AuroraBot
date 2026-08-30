from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from aurora import load_config
from aurora.config import collect_config
from aurora.configuration import models as models_module
from aurora.configuration.models import MODELS_CONFIG, ModelRuntimeConfig

if TYPE_CHECKING:
    from pathlib import Path

_MODELS = """\
[models.providers.deepseek]
adapter = "litellm"
secret_env = "DEEPSEEK_API_KEY"

[models.endpoints.default]
provider = "deepseek"
model = "deepseek-chat"

[models.runtime]
attempt_timeout_seconds = 90
max_attempts = 2
total_timeout_seconds = 180
max_output_tokens = 51200
"""


def _load_models(tmp_path: Path, content: str) -> models_module.ModelsConfig:
    config_directory = tmp_path / "config"
    config_directory.mkdir(exist_ok=True)
    (config_directory / "models.toml").write_text(content, encoding="utf-8")
    return collect_config(tmp_path, (models_module.register,)).get(MODELS_CONFIG)


def test_template_exports_frozen_typed_models_configuration(configured_project: Path) -> None:
    models = load_config(configured_project).get(MODELS_CONFIG)

    assert models.providers["deepseek"] == models_module.ProviderConfig("litellm", "DEEPSEEK_API_KEY")
    assert models.providers["siliconflow"] == models_module.ProviderConfig(
        "openai_compatible", "SILICONFLOW_API_KEY", base_url="https://api.siliconflow.cn/v1"
    )
    assert models.endpoints["default"] == models_module.ModelEndpointConfig("deepseek", "deepseek-chat")
    assert models.runtime == ModelRuntimeConfig(90.0, 2, 180.0, 51200)


def test_models_parses_exact_values(tmp_path: Path) -> None:
    models = _load_models(tmp_path, _MODELS)

    assert models.runtime == ModelRuntimeConfig(90.0, 2, 180.0, 51200)
    assert models.endpoints["default"].provider == "deepseek"
    assert models.providers["deepseek"].adapter == "litellm"


@pytest.mark.parametrize("field", ("attempt_timeout_seconds", "total_timeout_seconds"))
def test_models_reject_non_positive_timeouts(tmp_path: Path, field: str) -> None:
    content = _MODELS.replace(f"{field} = 90", f"{field} = 0").replace(f"{field} = 180", f"{field} = 0")
    with pytest.raises(ValueError, match="必须是有限正数"):
        _load_models(tmp_path, content)


def test_models_reject_unknown_provider_reference(tmp_path: Path) -> None:
    content = _MODELS.replace('provider = "deepseek"', 'provider = "ghost"')
    with pytest.raises(ValueError, match="未知 provider"):
        _load_models(tmp_path, content)


def test_models_require_at_least_one_provider_and_endpoint(tmp_path: Path) -> None:
    content = _MODELS.replace(
        '[models.providers.deepseek]\nadapter = "litellm"\nsecret_env = "DEEPSEEK_API_KEY"\n\n'
        '[models.endpoints.default]\nprovider = "deepseek"\nmodel = "deepseek-chat"\n\n',
        "[models.providers]\n[models.endpoints]\n\n",
    )
    with pytest.raises(ValueError, match="至少需要一个"):
        _load_models(tmp_path, content)


def test_models_reject_scalar_entry_in_provider_tables(tmp_path: Path) -> None:
    content = _MODELS.replace(
        "[models.providers.deepseek]",
        "[models.providers]\nbad = 1\n\n[models.providers.deepseek]",
    )
    with pytest.raises(ValueError, match="只包含命名表"):
        _load_models(tmp_path, content)


@pytest.mark.parametrize("base_url", ('"  "', "42"))
def test_models_reject_blank_or_non_text_base_url(tmp_path: Path, base_url: str) -> None:
    content = _MODELS.replace(
        'secret_env = "DEEPSEEK_API_KEY"',
        f'secret_env = "DEEPSEEK_API_KEY"\nbase_url = {base_url}',
    )
    with pytest.raises(ValueError, match="非空文本"):
        _load_models(tmp_path, content)


def test_models_reject_non_positive_output_budget(tmp_path: Path) -> None:
    content = _MODELS.replace("max_output_tokens = 51200", "max_output_tokens = 0")
    with pytest.raises(ValueError, match="正整数"):
        _load_models(tmp_path, content)


def test_model_runtime_rejects_non_positive_timeouts() -> None:
    with pytest.raises(ValueError, match="必须是有限正数"):
        ModelRuntimeConfig(0.0, 2, 180.0, 51200)


def test_model_runtime_rejects_total_shorter_than_attempt() -> None:
    with pytest.raises(ValueError, match="总超时"):
        ModelRuntimeConfig(90.0, 2, 60.0, 51200)


def test_model_runtime_rejects_non_integer_output_budget() -> None:
    with pytest.raises(ValueError, match="必须是正整数"):
        ModelRuntimeConfig(90.0, 2, 180.0, True)


def test_model_runtime_rejects_zero_output_budget() -> None:
    with pytest.raises(ValueError, match="必须是正整数"):
        ModelRuntimeConfig(90.0, 2, 180.0, 0)
