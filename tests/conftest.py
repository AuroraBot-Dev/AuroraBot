from __future__ import annotations

import shutil
from pathlib import Path

import pytest


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    source = Path(__file__).parents[1]
    shutil.copytree(source / "config", tmp_path / "config")
    shutil.copy2(source / "SOUL.md", tmp_path / "SOUL.md")
    (tmp_path / "config" / "nodes.toml").write_text(
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
    (tmp_path / "config" / "apps.toml").write_text(
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
