from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class CommandDecl:
    name: str
    description: str
    parameters: dict[str, dict[str, Any]] = field(default_factory=dict)
    returns: dict[str, dict[str, Any]] = field(default_factory=dict)

    # 从字典创建命令声明
    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CommandDecl":
        return cls(
            name=str(payload.get("name", "")).strip(),
            description=str(payload.get("description", "")).strip(),
            parameters=_normalize_mapping(payload.get("parameters")),
            returns=_normalize_mapping(payload.get("returns")),
        )

    # 将命令声明转换为参数模式
    def to_parameters_schema(self) -> dict[str, Any]:
        properties = {name: _schema_from_field(spec) for name, spec in self.parameters.items()}
        required = [
            name for name, spec in self.parameters.items() if bool(spec.get("required", True))
        ]
        return {"type": "object", "properties": properties, "required": required}

    # 将命令声明转换为返回模式
    def to_returns_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {name: _schema_from_field(spec) for name, spec in self.returns.items()},
        }


@dataclass(slots=True)
class Manifest:
    package: str
    name: str
    version: str
    brain_version: str
    app_desc: str = ""
    commands: list[CommandDecl] = field(default_factory=list)
    type: str = "application"

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        raw_payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
        payload = raw_payload if isinstance(raw_payload, dict) else {}
        raw_commands = payload.get("commands", [])
        if not isinstance(raw_commands, list):
            raw_commands = []
        commands = [CommandDecl.from_dict(item) for item in raw_commands if isinstance(item, dict)]
        return cls(
            package=str(payload.get("package", "")).strip(),
            name=str(payload.get("name", "")).strip(),
            version=str(payload.get("version", "0.0.0")).strip(),
            brain_version=str(payload.get("brain_version", "")).strip(),
            app_desc=str(payload.get("app_desc", "")).strip(),
            commands=commands,
            type=str(payload.get("type", "application")).strip() or "application",
        )


# 归一化映射
def _normalize_mapping(raw: object) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            normalized[str(key)] = {
                str(item_key): item_value for item_key, item_value in value.items()
            }
    return normalized


# 将字段规格转换为JSON模式
def _schema_from_field(spec: dict[str, Any]) -> dict[str, Any]:
    schema = {"type": str(spec.get("type", "string"))}
    description = str(spec.get("description", "")).strip()
    if description:
        schema["description"] = description
    items = spec.get("items")
    if isinstance(items, dict):
        schema["items"] = _schema_from_field({str(key): value for key, value in items.items()})
    return schema
