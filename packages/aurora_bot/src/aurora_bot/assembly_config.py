"""默认单 bot 装配的 TOML 配置结构及显式状态地址。"""

from typing import NotRequired, TypedDict, cast

from aurora_adapter.model import JsonValue
from aurora_config import ConfigSchema
from aurora_core.ids import Id
from aurora_core.json_data import encode_json

CONFIG = Id("org.aurora.bot:state/config")
AGENTS = Id("org.aurora.bot:state/agents")
MESSAGES = Id("org.aurora.bot:state/messages")
RUN = Id("org.aurora.bot:state/run")
WORK = Id("org.aurora.bot:state/react_work")


class ToolSelection(TypedDict):
    tool: str
    instance_id: str
    config: dict[str, JsonValue]


class ContextViewConfig(TypedDict):
    enabled: bool
    events: bool
    environment: bool
    notes: bool
    actions: bool
    max_chars: int


class ArchiveConfig(TypedDict):
    enabled: bool
    max_chars: int


class ContextManagementConfig(TypedDict):
    enabled: bool
    tool_result_chars: int
    summary_chars: int
    timeout_seconds: float


class BotConfig(TypedDict):
    instance_id: str
    model_role: str
    tools: list[ToolSelection]
    max_iterations: NotRequired[int]
    tool_timeout: float
    streaming: bool
    system_prompt: str
    context_view: ContextViewConfig
    notes: dict[str, bool]
    input_budget: ArchiveConfig
    context_management: ContextManagementConfig
    archive: ArchiveConfig
    actions: ArchiveConfig
    self_control: dict[str, bool]


def validate_json(value: object) -> None:
    encode_json(value)


def _check_tools(value: object) -> None:
    tools = cast(dict, value)["tools"]
    instances = [item["instance_id"] for item in tools]
    if len(instances) != len(set(instances)):
        raise ValueError("工具实例身份重复")
    config = cast(dict, value)
    management = config["context_management"]
    if management["enabled"]:
        if not config["input_budget"]["enabled"] or not config["actions"]["enabled"]:
            raise ValueError("上下文管理需要启用输入预算和行动证据")
        if management["summary_chars"] > config["input_budget"]["max_chars"] // 4:
            raise ValueError("摘要预算不能超过完整输入预算的四分之一")


_TEXT = {"type": "string", "minLength": 1}
BOT_SCHEMA = ConfigSchema(
    {
        "type": "object",
        "required": ["instance_id", "model_role"],
        "additionalProperties": False,
        "properties": {
            "instance_id": _TEXT,
            "model_role": _TEXT,
            "max_iterations": {"type": "integer", "minimum": 1},
            "tool_timeout": {"type": "number", "exclusiveMinimum": 0, "default": 30.0},
            "streaming": {"type": "boolean", "default": True},
            "system_prompt": {"type": "string", "default": ""},
            "context_view": {
                "type": "object",
                "additionalProperties": False,
                "default": {},
                "properties": {
                    "enabled": {"type": "boolean", "default": True},
                    "events": {"type": "boolean", "default": True},
                    "environment": {"type": "boolean", "default": True},
                    "notes": {"type": "boolean", "default": True},
                    "actions": {"type": "boolean", "default": True},
                    "max_chars": {"type": "integer", "minimum": 1024, "default": 12000},
                },
            },
            "input_budget": {
                "type": "object",
                "additionalProperties": False,
                "default": {},
                "properties": {
                    "enabled": {"type": "boolean", "default": False},
                    "max_chars": {"type": "integer", "minimum": 1024, "default": 128000},
                },
            },
            "context_management": {
                "type": "object",
                "additionalProperties": False,
                "default": {},
                "properties": {
                    "enabled": {"type": "boolean", "default": False},
                    "tool_result_chars": {"type": "integer", "minimum": 2048, "maximum": 32000, "default": 6000},
                    "summary_chars": {"type": "integer", "minimum": 256, "maximum": 16000, "default": 6000},
                    "timeout_seconds": {"type": "number", "exclusiveMinimum": 0, "default": 60.0},
                },
            },
            "notes": {
                "type": "object",
                "additionalProperties": False,
                "default": {},
                "properties": {"enabled": {"type": "boolean", "default": False}},
            },
            "self_control": {
                "type": "object",
                "additionalProperties": False,
                "default": {},
                "properties": {"enabled": {"type": "boolean", "default": False}},
            },
            "archive": {
                "type": "object",
                "additionalProperties": False,
                "default": {},
                "properties": {
                    "enabled": {"type": "boolean", "default": False},
                    "max_chars": {"type": "integer", "minimum": 1024, "maximum": 32000, "default": 8000},
                },
            },
            "actions": {
                "type": "object",
                "additionalProperties": False,
                "default": {},
                "properties": {
                    "enabled": {"type": "boolean", "default": False},
                    "max_chars": {"type": "integer", "minimum": 1024, "maximum": 32000, "default": 8000},
                },
            },
            "tools": {
                "type": "array",
                "default": [],
                "items": {
                    "type": "object",
                    "required": ["tool", "instance_id"],
                    "additionalProperties": False,
                    "properties": {
                        "tool": {"type": "string", "format": "aurora-id"},
                        "instance_id": _TEXT,
                        "config": {"type": "object", "default": {}},
                    },
                },
            },
        },
    },
    check=_check_tools,
)


def parse_config(value: object) -> BotConfig:
    """统一校验结构、缺省值、工具身份及上下文管理依赖。"""
    return cast(BotConfig, BOT_SCHEMA.parse(value))
