"""Hatch 发布钩子：只读核对声明，附带完整静态目录与契约来源。"""

import tomllib
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

from . import generate, sources


class MetadataBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = Path(self.root)
        generate(root, check=True)
        if self.target_name == "wheel":
            metadata = {str(root / "plugin.meta.json"): "plugin.meta.json"}
            project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
            for source in sources(project):
                path = root / source["manifest"]
                metadata[str(path)] = source["manifest"]
                manifest = tomllib.loads(path.read_text(encoding="utf-8"))
                for contract in manifest.get("contracts", {}).values():
                    if "file" in contract:
                        path = (root / source["manifest"]).parent / contract["file"]
                    else:
                        module = contract["export"].split(":")[0]
                        path = root / "src" / (module.replace(".", "/") + ".py")
                    metadata[str(path)] = path.relative_to(root).as_posix()
            build_data["extra_metadata"] = metadata
