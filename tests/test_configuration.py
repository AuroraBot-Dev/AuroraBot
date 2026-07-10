from __future__ import annotations

from pathlib import Path

import pytest

from src.localhost.configuration import ConfigurationError, load_configuration


def test_loads_deterministic_configuration_snapshot(project_root: Path) -> None:
    configuration = load_configuration(project_root)

    assert configuration.runtime.profile == "dev"
    assert configuration.runtime.workspace == project_root / "data" / "kernel"
    assert configuration.soul_hash
    assert configuration.edges == {"message.received": ("builtin.decide",)}
    assert configuration.adapters[0].capabilities == frozenset({"debug.echo"})


def test_rejects_non_loopback_production_debug_host(project_root: Path) -> None:
    config = project_root / "config" / "profiles" / "prod.toml"
    config.write_text('[runtime]\ndebug_host = "0.0.0.0"\n\n[logging]\nlevel = "INFO"\n', encoding="utf-8")

    with pytest.raises(ConfigurationError, match="loopback"):
        load_configuration(project_root, "prod")


def test_rejects_unknown_profile_configuration(project_root: Path) -> None:
    config = project_root / "config" / "profiles" / "dev.toml"
    config.write_text('[unknown]\nvalue = "not allowed"\n', encoding="utf-8")

    with pytest.raises(ConfigurationError, match="unexpected"):
        load_configuration(project_root)
