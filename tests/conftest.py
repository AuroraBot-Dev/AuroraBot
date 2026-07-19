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

[runtime.agents]
root_profile = "builtin.gate"
worker_profile = "builtin.worker"
max_active_agents = 16
max_agents_per_task = 8
max_depth = 3
max_children_per_agent = 4
turn_concurrency = 8
model_concurrency = 4
effect_concurrency = 8
blocking_workers = 4
lease_seconds = 30.0
ambient_ttl_seconds = 1800.0

[dashboard]
host = "127.0.0.1"
port = 8000
database_path = "data/dashboard/chat.sqlite3"
upload_dir = "data/dashboard/uploads"
max_upload_bytes = 67108864
session_ttl_seconds = 604800
allowed_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]

[dashboard.bot]
username = "aurorabot"
display_name = "AuroraBot"
avatar_url = ""

[soul]
path = "config/prompts/SOUL.md"

[logging]
level = "INFO"

[storage]
data_dir = "data"

[models.roles.fast]
provider = "test"
model = "fast"
capabilities = ["chat", "stream", "structured_output", "json_text_fallback", "tools"]

[models.roles.agent]
provider = "test"
model = "agent"
endpoint = "responses"
capabilities = ["chat", "stream", "structured_output", "json_text_fallback", "tools", "native_responses"]

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
    (config / "preference.toml").write_text(
        """[platform.console]
enabled = true
terminal_logs = false

[platform.dashboard]
enabled = true
open_browser = false

[platform.mcp]
enabled = true
terminal_logs = true
""",
        encoding="utf-8",
    )
    (prompts / "SOUL.md").write_text("You are the AuroraBot test fixture.", encoding="utf-8")
    (config / "agents.toml").write_text(
        """[[agent]]
id = "builtin.gate"
implementation = "src.agents.tool_agent:ToolAgent"
model_role = "fast"
prompt = "Gate and complete the task."
capabilities = ["org.aurora.console.send_message"]
can_delegate = true
child_profiles = ["builtin.worker"]

[[agent]]
id = "builtin.worker"
implementation = "src.agents.tool_agent:ToolAgent"
model_role = "agent"
prompt = "Complete the delegated task and report to the parent."
capabilities = ["org.aurora.console.send_message"]
can_delegate = true
child_profiles = ["builtin.worker"]
""",
        encoding="utf-8",
    )
    (config / "apps.toml").write_text(
        """app = []
""",
        encoding="utf-8",
    )
    return tmp_path
