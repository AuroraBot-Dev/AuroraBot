"""从发行声明和插件清单生成纯声明模块与静态目录；--check 只读核对。"""

import argparse
import json
import runpy
import tomllib
from pathlib import Path


def outputs(root: Path) -> dict[Path, str]:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    manifest = tomllib.loads((root / "plugin.meta.toml").read_text(encoding="utf-8"))
    if manifest["schema_version"] != 1:
        raise ValueError("不支持的插件清单版本")
    definitions = manifest["definitions"]
    identities = [item["id"] for item in definitions.values()]
    if len(set(identities)) != len(identities):
        raise ValueError("插件清单包含重复公共 ID")
    for item in definitions.values():
        if "slot" in item or "connect_to" in item:
            raise ValueError("插头清单不能指定运行连接")

    def reference(value):
        if value is None:
            return "None"
        return value["local"] if "local" in value else f"Id({value['id']!r})"

    lines = [
        '"""由 build_meta.py 生成；公共定义的唯一编辑来源为 plugin.meta.toml。"""',
        "from aurora_core.components import ComponentDeclaration, Definition, PluginDeclaration",
        "from aurora_core.ids import Id",
        "",
    ]
    lines.extend(f"{symbol} = Id({item['id']!r})" for symbol, item in definitions.items())
    for symbol, plugin in manifest["plugins"].items():
        name = plugin["entry_point"]
        plugin["factory"] = project["entry-points"]["aurora.plugins"][name]
        lines.extend(["", f"{symbol}_plugin = PluginDeclaration(", f"    name={name!r},", "    definitions=("])
        for key, item in definitions.items():
            if item["plugin"] != symbol:
                continue
            interface = item.get("interface")
            if isinstance(interface, dict) and "definition" in interface:
                interface_code = reference(interface["definition"])
            else:
                interface_code = repr(interface)
            lines.append(
                f"        Definition({key}, {item['kind']!r}, {plugin.get('provider', name)!r}, "
                f"register_to={reference(item.get('register_to'))}, interface={interface_code}),"
            )
        lines.extend(["    ),", f"    requires={tuple(plugin.get('requires', ()))!r},", "    components={"])
        for key, component in manifest.get("components", {}).items():
            if component["plugin"] != symbol:
                continue
            if component.get("slots"):
                raise ValueError("本阶段只支持方法插头和 core 生命周期槽；业务插槽将在其插件迁移时接入")
            plugs = component.get("plugs", [])
            for plug in plugs:
                if definitions[plug]["plugin"] != symbol:
                    raise ValueError(f"组件 {key} 导出了其他插件的定义")
            expression = "(" + "".join(f"{plug}, " for plug in plugs) + ")"
            lines.append(
                f"        {key!r}: ComponentDeclaration(inject={tuple(component.get('inject', ()))!r}, plugs={expression}),"
            )
        lines.extend(["    },", ").bind", ""])

    for contract in manifest.get("contracts", {}).values():
        if ("file" in contract) == ("export" in contract):
            raise ValueError("契约须指定 file 或 export 之一")
        if "file" in contract:
            contract["content"] = json.loads((root / contract["file"]).read_text(encoding="utf-8"))
        else:
            module, function = contract["export"].split(":")
            # 纯导出文件独立执行，不导入插件入口或构造运行服务。
            contract["content"] = runpy.run_path(str(root / "src" / (module.replace(".", "/") + ".py")))[function]()
    manifest["distribution"] = project
    return {
        root / "src/aurora_config/_meta.py": "\n".join(lines),
        root / "plugin.meta.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    }


def generate(root: Path, *, check: bool) -> None:
    for path, content in outputs(root).items():
        if check:
            # Python 生成物允许格式器调整排版，仍逐节点核对声明。
            if path.suffix == ".py":
                import ast

                actual = ast.dump(ast.parse(path.read_text(encoding="utf-8"))) if path.exists() else ""
                expected = ast.dump(ast.parse(content))
            else:
                actual = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
                expected = json.loads(content)
            if actual != expected:
                raise ValueError(f"插件元信息产物缺失或过期：{path}")
        else:
            path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args()
    generate(Path(__file__).resolve().parent, check=options.check)
