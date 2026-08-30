"""注册并解析 ``config/cadence.toml`` 的节律策略配置。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from aurora.config import ConfigKey
from aurora.utils.toml import (
    TomlTable,
    boolean,
    check_positive_integer,
    check_positive_number,
    load_toml,
    non_empty_text,
    optional_strings,
    optional_table_array,
    positive_integer,
    positive_number,
    table,
    text,
    text_array,
)

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector


@dataclass(frozen=True, slots=True)
class ReactiveRuleConfig:
    source: str
    event_kind: str
    agent: str
    contains_any: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        non_empty_text(self.source, "source")
        non_empty_text(self.event_kind, "event_kind")
        non_empty_text(self.agent, "agent")
        text_array(self.contains_any, "contains_any")


@dataclass(frozen=True, slots=True)
class CadenceConfig:
    enabled: bool
    agent: str
    evoke_every: int
    tick_seconds: int
    poll_seconds: float
    reactive: tuple[ReactiveRuleConfig, ...]

    def __post_init__(self) -> None:
        non_empty_text(self.agent, "agent")
        check_positive_integer(self.evoke_every, "evoke_every")
        check_positive_integer(self.tick_seconds, "tick_seconds")
        check_positive_number(self.poll_seconds, "poll_seconds")


CADENCE_CONFIG = ConfigKey[CadenceConfig]("cadence")


def register(configs: ConfigCollector) -> None:
    configs.register(CADENCE_CONFIG, "config/cadence.toml", _parse)


def _parse(path: Path) -> CadenceConfig:
    cadence = table(load_toml(path), "cadence")
    return CadenceConfig(
        boolean(cadence, "enabled"),
        text(cadence, "agent"),
        positive_integer(cadence, "evoke_every"),
        positive_integer(cadence, "tick_seconds"),
        positive_number(cadence, "poll_seconds"),
        _reactive_rules(cadence),
    )


def _reactive_rules(cadence: TomlTable) -> tuple[ReactiveRuleConfig, ...]:
    raw_rules = optional_table_array(cadence, "reactive")
    rules: list[ReactiveRuleConfig] = []
    for item in raw_rules:
        rules.append(
            ReactiveRuleConfig(
                text(item, "source"),
                text(item, "event_kind"),
                text(item, "agent"),
                optional_strings(item, "contains_any"),
            )
        )
    return tuple(rules)
