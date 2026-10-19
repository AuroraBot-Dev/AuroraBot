"""端点和提供方具有独立的原生资源身份，不能隐式混用。"""

import pytest

from src.ai.config import EndpointConfig, ProviderConfig
from src.contracts import ChatMessage, ModelRequest


@pytest.mark.parametrize("name", ["default", "lab:ai/provider/default", "lab:memory/model/tgn"])
def test_model_request_rejects_incomplete_or_wrong_kind_endpoint(name: str) -> None:
    """每次推理必须明确选择端点，其他资源不能被当作模型名字。"""
    with pytest.raises(ValueError, match="模型资源身份"):
        ModelRequest(name, (ChatMessage.system("主体身份"),))


def test_configuration_uses_separate_endpoint_and_provider_kinds() -> None:
    """配置引用使用完整身份，远端模型名称不被当作本地资源重写。"""
    provider = ProviderConfig("lab:ai/provider/service", "litellm", "SERVICE_KEY")
    endpoint = EndpointConfig("lab:ai/endpoint/main", provider.name, "vendor/opaque-model")
    assert endpoint.model == "vendor/opaque-model"
    with pytest.raises(ValueError, match="模型资源身份"):
        EndpointConfig("lab:ai/endpoint/main", "service", endpoint.model)
    with pytest.raises(ValueError, match="模型资源身份"):
        ProviderConfig(endpoint.name, "litellm", "SERVICE_KEY")
