from __future__ import annotations

import json
import unittest
import tempfile
from pathlib import Path

import yaml

from src.platform.manifest import CommandDecl, Manifest, _schema_from_field


class CommandDeclTest(unittest.TestCase):
    """CommandDecl schema 生成测试。"""

    def test_to_parameters_schema_basic(self) -> None:
        decl = CommandDecl(
            name="test_cmd",
            description="测试命令",
            parameters={
                "name": {"type": "string", "description": "用户名", "required": True},
                "age": {"type": "number", "required": False},
            },
        )
        schema = decl.to_parameters_schema()
        self.assertEqual(schema["type"], "object")
        self.assertIn("name", schema["properties"])
        self.assertIn("age", schema["properties"])
        self.assertEqual(schema["properties"]["name"]["type"], "string")
        self.assertEqual(schema["properties"]["name"]["description"], "用户名")
        self.assertEqual(schema["properties"]["age"]["type"], "number")
        self.assertIn("name", schema["required"])
        self.assertNotIn("age", schema["required"])

    def test_to_parameters_schema_default_required(self) -> None:
        decl = CommandDecl(
            name="test_cmd",
            description="",
            parameters={
                "text": {"type": "string"},
            },
        )
        schema = decl.to_parameters_schema()
        # 未指定 required 时默认视为必填
        self.assertIn("text", schema["required"])

    def test_to_parameters_schema_empty(self) -> None:
        decl = CommandDecl(name="cmd", description="")
        schema = decl.to_parameters_schema()
        self.assertEqual(schema["type"], "object")
        self.assertEqual(schema["properties"], {})
        self.assertEqual(schema["required"], [])

    def test_to_returns_schema(self) -> None:
        decl = CommandDecl(
            name="cmd",
            description="",
            returns={
                "success": {"type": "boolean", "description": "是否成功"},
            },
        )
        schema = decl.to_returns_schema()
        self.assertEqual(schema["type"], "object")
        self.assertIn("success", schema["properties"])
        self.assertEqual(schema["properties"]["success"]["type"], "boolean")

    def test_from_dict(self) -> None:
        decl = CommandDecl.from_dict(
            {
                "name": "my_cmd",
                "description": "描述",
                "parameters": {
                    "x": {"type": "string", "required": True},
                },
                "returns": {
                    "result": {"type": "string"},
                },
            }
        )
        self.assertEqual(decl.name, "my_cmd")
        self.assertEqual(decl.description, "描述")
        self.assertEqual(decl.parameters["x"]["type"], "string")
        self.assertEqual(decl.returns["result"]["type"], "string")

    def test_from_dict_handles_scalars(self) -> None:
        decl = CommandDecl.from_dict(
            {
                "name": "cmd",
                "description": "desc",
                "parameters": "not_a_dict",
                "returns": 42,
            }
        )
        self.assertEqual(decl.parameters, {})
        self.assertEqual(decl.returns, {})

    def test_nested_schema(self) -> None:
        schema = _schema_from_field(
            {
                "type": "array",
                "items": {"type": "string"},
            }
        )
        self.assertEqual(schema["type"], "array")
        self.assertIn("items", schema)
        self.assertEqual(schema["items"]["type"], "string")


class ManifestLoadTest(unittest.TestCase):
    """Manifest.load 测试。"""

    def test_load_full_manifest(self) -> None:
        yaml_content = yaml.safe_dump(
            {
                "package": "com.example.test",
                "name": "TestApp",
                "version": "2.0.0",
                "brain_version": ">=5.0.0",
                "app_desc": "A test application.",
                "commands": [
                    {
                        "name": "do_thing",
                        "description": "Do a thing.",
                        "parameters": {
                            "input": {"type": "string", "required": True},
                        },
                        "returns": {
                            "output": {"type": "string"},
                        },
                    }
                ],
            },
            allow_unicode=True,
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", encoding="utf-8", delete=False
        ) as f:
            f.write(yaml_content)
            tmp_path = Path(f.name)

        try:
            manifest = Manifest.load(tmp_path)
            self.assertEqual(manifest.package, "com.example.test")
            self.assertEqual(manifest.name, "TestApp")
            self.assertEqual(manifest.version, "2.0.0")
            self.assertEqual(manifest.brain_version, ">=5.0.0")
            self.assertEqual(manifest.app_desc, "A test application.")
            self.assertEqual(manifest.type, "application")
            self.assertEqual(len(manifest.commands), 1)
            self.assertEqual(manifest.commands[0].name, "do_thing")
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_load_empty_manifest(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", encoding="utf-8", delete=False
        ) as f:
            f.write("")
            tmp_path = Path(f.name)

        try:
            manifest = Manifest.load(tmp_path)
            self.assertEqual(manifest.package, "")
            self.assertEqual(manifest.version, "0.0.0")
            self.assertEqual(manifest.commands, [])
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_load_manifest_commands_not_list(self) -> None:
        yaml_content = yaml.safe_dump(
            {
                "package": "com.example.test",
                "commands": "not_a_list",
            },
            allow_unicode=True,
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", encoding="utf-8", delete=False
        ) as f:
            f.write(yaml_content)
            tmp_path = Path(f.name)

        try:
            manifest = Manifest.load(tmp_path)
            self.assertEqual(manifest.commands, [])
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_load_invalid_yaml_raises_parser_error(self) -> None:
        """Manifest.load 不吞 YAML 解析异常 — 调用方自行处理。"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", encoding="utf-8", delete=False
        ) as f:
            # 故意写入非法 YAML（缩进不一致）
            f.write("key:\n  sub: a\n sub2: b\n")
            tmp_path = Path(f.name)

        try:
            with self.assertRaises(yaml.YAMLError):
                Manifest.load(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_load_commands_skips_non_dict_entries(self) -> None:
        yaml_content = yaml.safe_dump(
            {
                "package": "com.example.test",
                "commands": [
                    {"name": "valid", "description": "ok"},
                    "not_a_dict",
                    42,
                    {"name": "also_valid", "description": "also ok"},
                ],
            },
            allow_unicode=True,
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", encoding="utf-8", delete=False
        ) as f:
            f.write(yaml_content)
            tmp_path = Path(f.name)

        try:
            manifest = Manifest.load(tmp_path)
            self.assertEqual(len(manifest.commands), 2)
            self.assertEqual(manifest.commands[0].name, "valid")
            self.assertEqual(manifest.commands[1].name, "also_valid")
        finally:
            tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
