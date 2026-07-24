"""包级 TOML 配置快照契约。"""

from pathlib import Path

import pytest

from src.config.loader import load_configuration
from src.contracts.configuration import ConfigurationError

ROOT = Path(__file__).parents[1]


def test_configuration_uses_engine_and_storage_snapshots() -> None:
    configuration = load_configuration(ROOT)
    source_names = {source.path.name for source in configuration.sources}

    assert {"runtime.toml", "engine.toml", "storage.toml", "logging.toml"} <= source_names
    assert configuration.engine.workspace == ROOT / "data" / "engine"
    assert configuration.engine.workspace == configuration.storage.engine
    assert configuration.storage.memory == ROOT / "data" / "memory"
    assert configuration.dashboard.database_path.parent == configuration.storage.dashboard
    assert configuration.dashboard.upload_dir.parent == configuration.storage.dashboard
    assert configuration.logging_dir == ROOT / "logs"


def test_profile_only_changes_runtime_snapshot() -> None:
    production = load_configuration(ROOT, "prod")
    development = load_configuration(ROOT, "dev")

    assert production.runtime.profile == "prod"
    assert development.runtime.profile == "dev"
    assert production.engine == development.engine
    assert production.storage == development.storage


@pytest.mark.parametrize(
    "filename",
    (
        "runtime.toml",
        "engine.toml",
        "platforms.toml",
        "models.toml",
        "logging.toml",
        "storage.toml",
        "agents.toml",
        "apps.toml",
        "profiles/prod.toml",
    ),
)
def test_unknown_top_level_toml_keys_are_rejected(project_root: Path, filename: str) -> None:
    path = project_root / "config" / filename
    path.write_text(f"{path.read_text(encoding='utf-8')}\n[unknown]\nvalue = true\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match=r"unexpected|unsupported"):
        load_configuration(project_root)


def test_nonexistent_profile_is_rejected(project_root: Path) -> None:
    with pytest.raises(ConfigurationError, match="profile does not exist"):
        load_configuration(project_root, "missing")


@pytest.mark.parametrize(
    ("original", "replacement", "message"),
    (
        ('data_root = "data"', 'data_root = "../outside"', "stay within"),
        ('engine = "engine"', 'engine = "../engine"', "stay within"),
        ('memory = "memory"', 'memory = "engine/memory"', "must not overlap"),
    ),
)
def test_storage_paths_cannot_escape_or_overlap(
    project_root: Path,
    original: str,
    replacement: str,
    message: str,
) -> None:
    path = project_root / "config" / "storage.toml"
    path.write_text(path.read_text(encoding="utf-8").replace(original, replacement), encoding="utf-8")
    with pytest.raises(ConfigurationError, match=message):
        load_configuration(project_root)
