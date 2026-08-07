"""提示词清单与 Markdown 内容的启动快照加载。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.config.files import read_source, read_toml_snapshot
from src.config.helpers import _string
from src.contracts.configuration import (
    ConfigurationError,
    ConfigurationSource,
    PromptConfig,
)

if TYPE_CHECKING:
    from pathlib import Path


def load_prompts(config_dir: Path, sources: list[ConfigurationSource], profile_ids: frozenset[str]) -> PromptConfig:
    """加载提示词清单和 Markdown，使其成为启动配置快照的一部分。"""
    manifest, source = read_toml_snapshot(config_dir / "prompts.toml")
    sources.append(source)
    if set(manifest) != {"system", "agent"}:
        raise ConfigurationError("invalid prompt configuration: expected system and agent tables")
    system = manifest["system"]
    agents = manifest["agent"]
    if not isinstance(system, dict) or set(system) != {"soul", "world"}:
        raise ConfigurationError("invalid prompt configuration: system must contain soul and world")
    if not isinstance(agents, dict) or frozenset(agents) != profile_ids:
        raise ConfigurationError("invalid prompt configuration: agent profiles do not match agents.toml")

    entries = (
        ("system.soul", system["soul"]),
        ("system.world", system["world"]),
        *((f"agent.{profile_id}", raw_path) for profile_id, raw_path in agents.items()),
    )
    paths: dict[str, Path] = {}
    for label, raw_path in entries:
        path = (config_dir / _string(raw_path, f"prompt.{label}")).resolve()
        if not path.is_relative_to(config_dir) or path.suffix.lower() != ".md":
            raise ConfigurationError(f"invalid prompt configuration: {label} must be a Markdown file under config")
        paths[label] = path
    if len(paths) != len(set(paths.values())):
        raise ConfigurationError("invalid prompt configuration: prompt fragments must use distinct files")

    contents: dict[str, str] = {}
    prompt_sources = [source]
    for label, path in paths.items():
        raw, source = read_source(path)
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ConfigurationError(f"invalid prompt file {path}: file is not UTF-8") from error
        if label != "system.soul" and not content.strip():
            raise ConfigurationError(f"invalid prompt file {path}: file is empty")
        contents[label] = content
        sources.append(source)
        prompt_sources.append(source)
    return PromptConfig(
        soul=contents["system.soul"],
        world=contents["system.world"],
        agents={profile_id: contents[f"agent.{profile_id}"] for profile_id in sorted(profile_ids)},
        sources=tuple(prompt_sources),
    )
