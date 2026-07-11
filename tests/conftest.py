from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("AURORA_PROFILE", raising=False)
    config = tmp_path / "config"
    prompts = config / "prompts"
    profiles = config / "profiles"
    prompts.mkdir(parents=True)
    profiles.mkdir()
    (config / "aurora.toml").write_text(
        """[runtime]
profile = "test"
workspace = "data/kernel"
debug_host = "127.0.0.1"
debug_port = 8765

[soul]
path = "config/prompts/SOUL.md"

[logging]
level = "INFO"

[storage]
data_dir = "data"

[models.roles.fast]
provider = "test"
model = "fast"
capabilities = ["chat", "stream", "structured_output", "json_text_fallback"]

[models.roles.quality]
provider = "test"
model = "quality"
capabilities = ["chat", "stream", "structured_output", "json_text_fallback"]

[models.roles.multimodal]
provider = "test"
model = "multimodal"
capabilities = ["chat", "stream", "structured_output", "json_text_fallback", "vision"]

[models.roles.embedding]
provider = "test"
model = "embedding"
capabilities = ["embedding"]

[models.providers.test]
adapter = "litellm"
secret_env = "AURORA_TEST_MODEL_API_KEY"

[models.logging]
log_queries = false
log_responses = false
""",
        encoding="utf-8",
    )
    (prompts / "SOUL.md").write_text("You are the AuroraBot test fixture.", encoding="utf-8")
    (config / "nodes.toml").write_text(
        """[[node]]
id = "builtin.decide"
enabled = true
implementation = "src.nodes.decide:DecideNode"
inputs = ["message.received"]
outputs = ["effect.requested"]
capabilities = ["org.aurora.console.send_message"]
model_roles = []

[[node]]
id = "builtin.model_decide"
enabled = false
implementation = "src.nodes.model_decide:ModelDecideNode"
inputs = ["message.received"]
outputs = ["effect.requested"]
capabilities = ["org.aurora.console.send_message"]
model_roles = ["fast"]

[[edge]]
event_type = "message.received"
target = "builtin.decide"
""",
        encoding="utf-8",
    )
    (config / "apps.toml").write_text(
        """app = []

[[adapter]]
id = "local.test"
enabled = true
implementation = "src.platform.local:LocalTestPlatform"

[[adapter.capability]]
id = "org.aurora.console.send_message"
parameters_schema = { type = "object", properties = { text = { type = "string" } }, required = ["text"], additionalProperties = false }
""",
        encoding="utf-8",
    )
    return tmp_path
