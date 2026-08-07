"""包级 TOML 配置快照契约。"""

from pathlib import Path

import pytest

from src.config.loader import load_configuration
from src.contracts.configuration import ConfigurationError

ROOT = Path(__file__).parents[1]


def test_configuration_uses_engine_and_storage_snapshots() -> None:
    configuration = load_configuration(ROOT)
    source_names = {source.path.name for source in configuration.sources}

    assert {"runtime.toml", "engine.toml", "storage.toml", "logging.toml", "prompts.toml", "SOUL.md"} <= source_names
    assert configuration.engine.workspace == ROOT / "data" / "engine"
    assert configuration.engine.workspace == configuration.storage.engine
    assert configuration.storage.memory == ROOT / "data" / "memory"
    assert configuration.storage.platform == ROOT / "data" / "platform"
    assert configuration.storage.dashboard == ROOT / "data" / "platform" / "dashboard"
    assert configuration.storage.mcp == ROOT / "data" / "platform" / "mcp"
    assert configuration.storage.apps == ROOT / "data" / "platform" / "mcp" / "apps"
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


def test_profile_cannot_escape_profile_directory(project_root: Path) -> None:
    with pytest.raises(ConfigurationError, match="simple name"):
        load_configuration(project_root, "/tmp/external")


@pytest.mark.parametrize("value", ("nan", "inf", "-inf"))
def test_non_finite_runtime_limits_are_rejected(project_root: Path, value: str) -> None:
    path = project_root / "config" / "engine.toml"
    path.write_text(path.read_text(encoding="utf-8").replace("lease_seconds = 30.0", f"lease_seconds = {value}"))
    with pytest.raises(ConfigurationError, match="positive"):
        load_configuration(project_root)


def test_boolean_debug_port_is_rejected(project_root: Path) -> None:
    path = project_root / "config" / "runtime.toml"
    path.write_text(path.read_text(encoding="utf-8").replace("debug_port = 8765", "debug_port = true"))
    with pytest.raises(ConfigurationError, match="debug_port"):
        load_configuration(project_root)


def test_unknown_mcp_keys_and_invalid_env_names_are_rejected(project_root: Path) -> None:
    platforms = project_root / "config" / "platforms.toml"
    platforms.write_text(f"{platforms.read_text(encoding='utf-8')}\nstartup_timeout = 10\n")
    with pytest.raises(ConfigurationError, match="unexpected"):
        load_configuration(project_root)

    platforms.write_text((ROOT / "config" / "platforms.toml").read_text(encoding="utf-8"))
    apps = project_root / "config" / "apps.toml"
    apps.write_text(apps.read_text(encoding="utf-8").replace("env = []", 'env = ["BAD-NAME"]', 1))
    with pytest.raises(ConfigurationError, match="environment variable names"):
        load_configuration(project_root)


@pytest.mark.parametrize(
    ("original", "replacement", "message"),
    (
        ('data_root = "data"', 'data_root = "../outside"', "stay within"),
        ('engine = "engine"', 'engine = "../engine"', "stay within"),
        ('memory = "memory"', 'memory = "engine/memory"', "must not overlap"),
        ('apps_dir = "apps"', 'apps_dir = "."', "must not overlap"),
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
