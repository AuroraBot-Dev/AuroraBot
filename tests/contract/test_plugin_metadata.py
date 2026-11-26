"""核对唯一来源生成物与真实插件登记，不实例化服务或启动资源。"""

import json
import runpy
from pathlib import Path

from aurora_config import plugin
from aurora_config.editor_contract import describe_configuration

ROOT = Path(__file__).resolve().parents[2] / "packages/aurora_config"


def test_manifest_generated_catalog_and_runtime_definitions_agree():
    runpy.run_path(str(ROOT / "build_meta.py"))["generate"](ROOT, check=True)
    catalog = json.loads((ROOT / "plugin.meta.json").read_text(encoding="utf-8"))
    exported = plugin()
    definitions = {item["id"]: item for item in catalog["definitions"].values()}
    assert {str(entry.id) for entry in exported.entries} == definitions.keys()
    for entry in exported.entries:
        declaration = definitions[str(entry.id)]
        owner = catalog["plugins"][declaration["plugin"]]
        assert entry.provider == owner["entry_point"]
        assert entry.kind == declaration["kind"]
        assert str(entry.register_to) == declaration["register_to"]["id"]
        assert entry.slot is None
    assert catalog["contracts"]["configuration_http"]["content"] == describe_configuration()
