"""验证配置结构、缺省值、特殊校验与字段级错误。"""

import pytest
from aurora_config import ConfigSchema


def test_nested_defaults_are_validated_and_do_not_share_mutable_values():
    schema = ConfigSchema(
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "retries": {"type": "integer", "minimum": 0, "default": 2},
                        },
                    },
                },
                "profiles": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "object",
                        "properties": {
                            "enabled": {"type": "boolean", "default": True},
                        },
                    },
                },
                "tags": {"type": "array", "default": []},
            },
        }
    )
    value = {"tasks": [{}], "profiles": {"primary": {}}}
    parsed = schema.parse(value)
    assert parsed == {"tasks": [{"retries": 2}], "profiles": {"primary": {"enabled": True}}, "tags": []}
    assert value == {"tasks": [{}], "profiles": {"primary": {}}}
    assert isinstance(parsed, dict)
    parsed["tags"].append("changed")
    assert schema.parse({}) == {"tags": []}


@pytest.mark.parametrize("value", [True, 1.0, 0, "3"])
def test_integer_configuration_rejects_bool_float_and_invalid_range(value):
    schema = ConfigSchema({"type": "object", "properties": {"count": {"type": "integer", "minimum": 1}}})
    with pytest.raises(ValueError, match="count"):
        schema.parse({"count": value})


@pytest.mark.parametrize("value", [{}, {"mode": "secret-value"}, {"mode": "fast", "extra": True}])
def test_required_enum_and_unknown_fields_report_constraints_without_values(value):
    schema = ConfigSchema(
        {
            "type": "object",
            "required": ["mode"],
            "additionalProperties": False,
            "properties": {"mode": {"enum": ["fast", "steady"]}},
        }
    )
    with pytest.raises(ValueError) as caught:
        schema.parse(value)
    assert "配置字段" in str(caught.value)
    assert "secret-value" not in str(caught.value)


def test_public_id_validation_and_callback_use_normalized_independent_copy():
    seen = []

    def check(value):
        seen.append(dict(value))
        value["enabled"] = False

    schema = ConfigSchema(
        {
            "type": "object",
            "properties": {
                "target": {"type": "string", "format": "aurora-id"},
                "enabled": {"type": "boolean", "default": True},
            },
        },
        check=check,
    )
    assert schema.parse({"target": "dev.example:operations/run"}) == {
        "target": "dev.example:operations/run",
        "enabled": True,
    }
    assert seen == [{"target": "dev.example:operations/run", "enabled": True}]
    with pytest.raises(ValueError, match="target"):
        schema.parse({"target": "invalid"})
    assert len(seen) == 1


def test_invalid_default_is_rejected_and_boolean_schemas_are_supported():
    schema = ConfigSchema({"type": "object", "properties": {"count": {"type": "integer", "default": "invalid"}}})
    with pytest.raises(ValueError, match="count"):
        schema.parse({})
    assert ConfigSchema({"properties": {"optional": True}}).parse({}) == {}


def test_schema_does_not_retrieve_external_references():
    from referencing.exceptions import Unresolvable

    schema = ConfigSchema({"$ref": "https://invalid.example/config-schema"})
    with pytest.raises(Unresolvable):
        schema.parse({})
