"""注册并解析 ``config/cadence.toml`` 的节律策略配置。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from aurora.config import ConfigKey
from aurora.utils.toml import TomlTable, boolean, load_toml, positive_integer, table, text

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector


@dataclass(frozen=True, slots=True)
class ReactiveRuleConfig:
    source: str
    event_kind: str
    agent: str
    contains_any: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CadenceConfig:
    enabled: bool
    agent: str
    evoke_every: int
    tick_seconds: int
    poll_seconds: float
    reactive: tuple[ReactiveRuleConfig, ...]


CADENCE_CONFIG = ConfigKey[CadenceConfig]("cadence")


def register(configs: ConfigCollector) -> None:
    configs.register(CADENCE_CONFIG, "config/cadence.toml", _parse)


def _parse(path: Path) -> CadenceConfig:
    cadence = table(load_toml(path), "cadence")
    poll_seconds = cadence.get("poll_seconds")
    if not isinstance(poll_seconds, (int, float)) or isinstance(poll_seconds, bool) or poll_seconds <= 0:
        raise ValueError("配置字段 poll_seconds 必须是正数")
    return CadenceConfig(
        boolean(cadence, "enabled"),
        text(cadence, "agent"),
        positive_integer(cadence, "evoke_every"),
        positive_integer(cadence, "tick_seconds"),
        float(poll_seconds),
        _reactive_rules(cadence),
    )


def _reactive_rules(cadence: TomlTable) -> tuple[ReactiveRuleConfig, ...]:
    raw_rules = cadence.get("reactive", ())
    if not isinstance(raw_rules, tuple) or any(not isinstance(item, Mapping) for item in raw_rules):
        raise ValueError("cadence.reactive 必须是表数组")
    rules: list[ReactiveRuleConfig] = []
    for raw in raw_rules:
        item = cast("TomlTable", raw)
        raw_terms = item.get("contains_any", ())
        if not isinstance(raw_terms, tuple) or any(not isinstance(term, str) or not term.strip() for term in raw_terms):
            raise ValueError("cadence.reactive.contains_any 必须是非空文本数组")
        rules.append(
            ReactiveRuleConfig(
                text(item, "source"),
                text(item, "event_kind"),
                text(item, "agent"),
                tuple(term.strip() for term in raw_terms),
            )
        )
    return tuple(rules)
