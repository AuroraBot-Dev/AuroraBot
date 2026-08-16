"""包级 TOML 配置快照契约。"""

import sqlite3
from pathlib import Path

import pytest

from src.config.loader import load_configuration
from src.contracts import ConfigurationError

ROOT = Path(__file__).parents[1]


def test_test_process_cannot_connect_repository_runtime_database() -> None:
    probe = ROOT / "data" / "pytest-pollution-probe.sqlite3"
    with pytest.raises(RuntimeError, match="must not access repository runtime data"):
        sqlite3.connect(probe)
    assert not probe.exists()


def test_default_test_root_is_disposable(tmp_path: Path) -> None:
    assert Path.cwd() == tmp_path
    configuration = load_configuration(Path.cwd())
    assert configuration.storage.data_root == tmp_path / "data"


def test_configuration_uses_engine_and_storage_snapshots() -> None:
    configuration = load_configuration(ROOT)
    source_names = {source.path.name for source in configuration.sources}
    profiles = {profile.id: profile for profile in configuration.agents}

    assert {
        "runtime.toml",
        "engine.toml",
        "storage.toml",
        "logging.toml",
        "prompts.toml",
        "extensions.toml",
        "SOUL.md",
    } <= source_names
    assert configuration.engine.workspace == ROOT / "data" / "engine"
    assert configuration.engine.workspace == configuration.storage.engine
    assert configuration.storage.memory == ROOT / "data" / "memory"
    assert configuration.storage.platform == ROOT / "data" / "platform"
    assert configuration.storage.ops == ROOT / "data" / "ops"
    assert configuration.storage.mcp == ROOT / "data" / "platform" / "mcp"
    assert configuration.storage.apps == ROOT / "data" / "platform" / "mcp" / "apps"
    assert configuration.runtime.panel.host == "127.0.0.1"
    assert configuration.runtime.panel.port == 8765  # noqa: PLR2004
    assert configuration.runtime.panel.max_upload_bytes == 67108864  # noqa: PLR2004
    assert configuration.logging_dir == ROOT / "logs"
    assert profiles["builtin.triage"].child_profiles == frozenset({"builtin.fast", "builtin.root"})
    assert profiles["builtin.fast"].model_role == "fast"
    assert not profiles["builtin.fast"].can_delegate
    assert profiles["builtin.fast"].child_profiles == frozenset()
    assert configuration.engine.triage.max_interrupts == 2  # noqa: PLR2004
    assert configuration.engine.triage.max_generation_seconds == 45.0  # noqa: PLR2004
    extension_ids = {item.id for item in configuration.extensions}
    assert extension_ids == {"aurora.builtin.control", "aurora.builtin.memory"}


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
        "extensions.toml",
        "profiles/prod.toml",
    ),
)
def test_unknown_top_level_toml_keys_are_rejected(project_root: Path, filename: str) -> None:
    path = project_root / "config" / filename
    path.write_text(f"{path.read_text(encoding='utf-8')}\n[unknown]\nvalue = true\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match=r"unexpected|unsupported"):
        load_configuration(project_root)


def test_invalid_extension_face_is_rejected(project_root: Path) -> None:
    path = project_root / "config" / "extensions.toml"
    path.write_text(
        path.read_text(encoding="utf-8").replace('faces = ["control_action"]', 'faces = ["unknown_face"]'),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="unsupported face"):
        load_configuration(project_root)


def test_duplicate_extension_id_is_rejected(project_root: Path) -> None:
    path = project_root / "config" / "extensions.toml"
    original = path.read_text(encoding="utf-8")
    duplicate = original.replace(
        'id = "aurora.builtin.memory"',
        'id = "aurora.builtin.control"',
    )
    path.write_text(duplicate, encoding="utf-8")
    with pytest.raises(ConfigurationError, match="duplicate extension id"):
        load_configuration(project_root)


def test_nonexistent_profile_is_rejected(project_root: Path) -> None:
    with pytest.raises(ConfigurationError, match="profile does not exist"):
        load_configuration(project_root, "missing")


def test_profile_cannot_escape_profile_directory(project_root: Path) -> None:
    with pytest.raises(ConfigurationError, match="simple name"):
        load_configuration(project_root, "/tmp/external")

    profile = project_root / "config" / "profiles" / "dev.toml"
    external = project_root / "external.toml"
    external.write_bytes(profile.read_bytes())
    profile.unlink()
    profile.symlink_to(external)
    with pytest.raises(ConfigurationError, match="simple name"):
        load_configuration(project_root, "dev")


def test_profile_directory_symlink_and_empty_selector_are_rejected(project_root: Path) -> None:
    with pytest.raises(ConfigurationError, match="simple name"):
        load_configuration(project_root, "")

    profiles = project_root / "config" / "profiles"
    external = project_root / "external-profiles"
    profiles.rename(external)
    profiles.symlink_to(external, target_is_directory=True)
    with pytest.raises(ConfigurationError, match="simple name"):
        load_configuration(project_root, "dev")


@pytest.mark.parametrize("value", ("nan", "inf", "-inf"))
def test_non_finite_runtime_limits_are_rejected(project_root: Path, value: str) -> None:
    path = project_root / "config" / "engine.toml"
    path.write_text(path.read_text(encoding="utf-8").replace("turn_concurrency = 8", f"turn_concurrency = {value}"))
    with pytest.raises(ConfigurationError, match="positive"):
        load_configuration(project_root)


def test_boolean_panel_port_is_rejected(project_root: Path) -> None:
    path = project_root / "config" / "runtime.toml"
    path.write_text(path.read_text(encoding="utf-8").replace("port = 8765", "port = true"))
    with pytest.raises(ConfigurationError, match="port"):
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

    apps.write_text(apps.read_text(encoding="utf-8").replace('env = ["BAD-NAME"]', 'env = [{ name = "X" }]'))
    with pytest.raises(ConfigurationError, match="environment variable names"):
        load_configuration(project_root)


def test_prompt_agent_ids_do_not_collide_with_system_sections(project_root: Path) -> None:
    agents = project_root / "config" / "agents.toml"
    renamed = agents.read_text(encoding="utf-8").replace("builtin.root", "soul")
    agents.write_text(renamed)
    prompts = project_root / "config" / "prompts.toml"
    prompts.write_text(prompts.read_text(encoding="utf-8").replace('"builtin.root"', '"soul"'))
    engine = project_root / "config" / "engine.toml"
    engine.write_text(
        engine.read_text(encoding="utf-8").replace('root_profile = "builtin.triage"', 'root_profile = "soul"')
    )

    configuration = load_configuration(project_root)
    assert configuration.prompts.agents["soul"] != configuration.prompts.soul
    qq = next(app for app in configuration.apps if app.package == "org.aurora.qq")
    assert qq.env_vars == ("AURORA_QQ_TOKEN", "AURORA_QQ_CONFIG")


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
