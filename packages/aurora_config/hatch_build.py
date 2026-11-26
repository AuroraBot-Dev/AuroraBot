"""发布前核对生成物，把静态目录与清单写入发行元数据。"""

import runpy
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = Path(self.root)
        runpy.run_path(str(root / "build_meta.py"))["generate"](root, check=True)
        if self.target_name == "wheel":
            build_data["extra_metadata"] = {
                str(root / "plugin.meta.json"): "plugin.meta.json",
                str(root / "plugin.meta.toml"): "plugin.meta.toml",
                str(root / "src/aurora_config/editor_contract.py"): "editor_contract.py",
            }
