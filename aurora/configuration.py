"""组合根使用的一份最小 TOML 配置。"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.prompt import PromptCatalog

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class RootAgentConfiguration:
    node_id: str
    profile: str
    model: str
    tools: frozenset[str]


@dataclass(frozen=True, slots=True)
class RunnerConfiguration:
    max_depth: int = 4
    max_nodes: int = 32
    max_steps: int = 256
    max_prompt_characters: int = 32_000


@dataclass(frozen=True, slots=True)
class AuroraConfiguration:
    root: RootAgentConfiguration
    runner: RunnerConfiguration
    prompt: PromptCatalog


def load_configuration(project_root: Path) -> AuroraConfiguration:
    path = project_root / "config" / "aurora.toml"
    with path.open("rb") as stream:
        document = tomllib.load(stream)
    root = _table(document, "root")
    runner = _table(document, "runner")
    prompt = _table(document, "prompt")
    profiles = _table(prompt, "profiles")
    configuration = AuroraConfiguration(
        RootAgentConfiguration(
            _text(root, "node_id"),
            _text(root, "profile"),
            _text(root, "model"),
            frozenset(_strings(root, "tools")),
        ),
        RunnerConfiguration(
            _positive_integer(runner, "max_depth"),
            _positive_integer(runner, "max_nodes"),
            _positive_integer(runner, "max_steps"),
            _positive_integer(runner, "max_prompt_characters"),
        ),
        PromptCatalog(_strings(prompt, "system"), {key: str(value) for key, value in profiles.items()}),
    )
    if configuration.root.profile not in configuration.prompt.profiles:
        raise ValueError(f"missing prompt for root profile {configuration.root.profile}")
    return configuration


def _table(value: dict[str, Any], key: str) -> dict[str, Any]:
    result = value.get(key)
    if not isinstance(result, dict):
        raise ValueError(f"configuration requires [{key}] table")
    return result


def _text(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise ValueError(f"configuration requires non-empty {key}")
    return result.strip()


def _strings(value: dict[str, Any], key: str) -> tuple[str, ...]:
    result = value.get(key)
    if not isinstance(result, list) or any(not isinstance(item, str) or not item.strip() for item in result):
        raise ValueError(f"configuration requires string array {key}")
    return tuple(item.strip() for item in result)


def _positive_integer(value: dict[str, Any], key: str) -> int:
    result = value.get(key)
    if not isinstance(result, int) or isinstance(result, bool) or result <= 0:
        raise ValueError(f"configuration requires positive integer {key}")
    return result
