"""文件输入形状、能力与二进制预算边界。"""

import base64

import pytest
from aurora_adapter.model import ChatCapabilities, ModelConfig, UnsupportedCapability, require_capabilities
from aurora_adapter.model.content import MAX_FILE_BYTES, request_size, validate_content
from aurora_adapter.model.testing import FakeModel, FakeReply


@pytest.mark.parametrize(
    "content",
    [
        [],
        [{"type": "path", "path": "C:/secret.txt"}],
        [{"type": "image_url", "image_url": {"url": "file:///C:/secret.png"}}],
        [{"type": "image_url", "image_url": {"url": "http://example.test/a.png"}}],
        [{"type": "image_url", "image_url": {"url": "data:application/pdf;base64,eA=="}}],
        [{"type": "image_url", "image_url": {"url": "data:image/png;base64,%%%"}}],
        [{"type": "file", "file": {"file_id": "a", "file_data": "data:text/plain;base64,eA=="}}],
        [{"type": "file", "file": {"file_id": "C:/secret.txt"}}],
        [{"type": "file", "file": {"file_id": "data:application/pdf;base64,eA=="}}],
        [{"type": "file", "file": {"file_data": "https://example.test/sample.pdf"}}],
        [{"type": "file", "file": {"file_data": "data:text/plain;base64,"}}],
    ],
)
def test_invalid_content_rejected(content):
    with pytest.raises(ValueError):
        validate_content(content)


def test_binary_size_and_primary_multimodal_default():
    data = base64.b64encode(b"x" * 2048).decode()
    content = [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}}]
    request = {"messages": [{"role": "user", "content": content}]}
    assert validate_content(content) == content
    chars, binary = request_size(request)
    assert chars < 200 and binary == 2048
    require_capabilities(FakeModel(lambda _: FakeReply()), request, streaming=True)
    with pytest.raises(UnsupportedCapability, match="文件输入"):
        require_capabilities(
            FakeModel(lambda _: FakeReply(), capabilities=ChatCapabilities(file_input=False)), request, streaming=True
        )


def test_combined_file_limit():
    data = base64.b64encode(b"x" * (MAX_FILE_BYTES // 2 + 1)).decode()
    part = {"type": "file", "file": {"file_data": f"data:application/pdf;base64,{data}"}}
    with pytest.raises(ValueError, match="合计"):
        validate_content([part, part])


@pytest.mark.parametrize(
    "thinking",
    [{"type": "enabled", "budget_tokens": 1}, {"type": "disabled", "budget_tokens": 1024}, {"type": "unknown"}],
)
def test_invalid_thinking_config_rejected(thinking):
    with pytest.raises(ValueError, match="thinking"):
        ModelConfig("model", thinking=thinking)
