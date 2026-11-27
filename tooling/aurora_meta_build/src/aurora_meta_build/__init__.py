"""生成插件声明和版本 2 发行目录；仅使用标准库，不导入运行包。"""

import argparse
import ast
import json
import runpy
import tomllib
from importlib.metadata import distribution
from pathlib import Path


def _manifest(root: Path, path: Path, project: dict) -> dict:
    manifest = tomllib.loads(path.read_text(encoding="utf-8"))
    if manifest["schema_version"] != 2 or len(manifest["plugins"]) != 1:
        raise ValueError("版本 2 的每份清单须描述一个公开插件")
    for plugin in manifest["plugins"].values():
        plugin["factory"] = project["entry-points"]["aurora.plugins"][plugin["entry_point"]]
    for item in manifest["definitions"].values():
        if "slot" in item or "connect_to" in item:
            raise ValueError("插头清单不能指定运行连接")
    for contract in manifest.get("contracts", {}).values():
        if ("file" in contract) == ("export" in contract):
            raise ValueError("契约须指定 file 或 export 之一")
        if "file" in contract:
            contract["content"] = json.loads((path.parent / contract["file"]).read_text(encoding="utf-8"))
        else:
            module, function = contract["export"].split(":")
            contract["content"] = runpy.run_path(str(root / "src" / (module.replace(".", "/") + ".py")))[function]()
    return manifest


def _module(manifest: dict) -> str:
    definitions = manifest["definitions"]

    def reference(value):
        if value is None:
            return "None"
        return value["local"] if "local" in value else f"Id({value['id']!r})"

    def ports(component, kind):
        names = component.get(kind, [])
        for name in names:
            definitions[name]
        return "(" + "".join(f"{name}, " for name in names) + ")"

    lines = [
        '"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""',
        "from aurora_core.components import ComponentDeclaration, Definition, PluginDeclaration",
        "from aurora_core.ids import Id",
        "",
    ]
    lines.extend(f"{symbol} = Id({item['id']!r})" for symbol, item in definitions.items())
    for symbol, plugin in manifest["plugins"].items():
        name = plugin["entry_point"]
        lines.extend(["", f"{symbol}_plugin = PluginDeclaration(", f"    name={name!r},", "    definitions=("])
        for key, item in definitions.items():
            if item["plugin"] != symbol:
                raise ValueError(f"定义 {key} 不属于本清单插件")
            interface = item.get("interface")
            interface_code = (
                reference(interface["definition"])
                if isinstance(interface, dict) and "definition" in interface
                else repr(interface)
            )
            lines.append(
                f"        Definition({key}, {item['kind']!r}, {plugin.get('provider', name)!r}, "
                f"register_to={reference(item.get('register_to'))}, interface={interface_code}),"
            )
        lines.extend(["    ),", f"    requires={tuple(plugin.get('requires', ()))!r},", "    components={"])
        for key, component in manifest.get("components", {}).items():
            if component["plugin"] != symbol:
                raise ValueError(f"组件 {key} 不属于本清单插件")
            options = manifest["contracts"][component["options"]]["content"] if "options" in component else None
            fields = [f"{kind}={ports(component, kind)}" for kind in ("plugs", "slots")]
            fields += [
                f"{kind}={tuple(component.get(kind, ()))!r}" for kind in ("inject", "states", "resources", "inputs")
            ]
            fields.append(f"options={options!r}")
            lines.append(f"        {key!r}: ComponentDeclaration({', '.join(fields)}),")
        lines.extend(["    },", ").bind", ""])
    return "\n".join(lines)


def outputs(root: Path) -> dict[Path, str]:
    """每份清单使用自己的符号表；发行目录保留来源相对路径。"""
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    catalog = {"schema_version": 2, "distribution": project, "manifests": {}}
    result = {}
    identities, names = set(), set()
    for source in pyproject["tool"]["aurora-meta-build"]["plugins"]:
        manifest = _manifest(root, root / source["manifest"], project)
        for item in manifest["definitions"].values():
            identity = item["id"]
            if identity in identities:
                raise ValueError(f"发行目录包含重复公共 ID：{identity}")
            identities.add(identity)
        for plugin in manifest["plugins"].values():
            name = plugin["entry_point"]
            if name in names:
                raise ValueError(f"发行目录包含重复插件：{name}")
            names.add(name)
        catalog["manifests"][source["manifest"]] = manifest
        result[root / source["module"]] = _module(manifest)
    result[root / "plugin.meta.json"] = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
    return result


def generate(root: Path, *, check: bool = False) -> None:
    """开发时生成；发布构建只读比较 AST 和 JSON，不改写源文件。"""
    for path, content in outputs(root).items():
        if check:
            if path.suffix == ".py":
                actual = ast.dump(ast.parse(path.read_text(encoding="utf-8"))) if path.exists() else ""
                expected = ast.dump(ast.parse(content))
            else:
                actual = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
                expected = json.loads(content)
            if actual != expected:
                raise ValueError(f"插件元信息产物缺失或过期：{path}")
        else:
            path.write_text(content, encoding="utf-8")


def read_catalog(name: str) -> dict:
    """从安装的发行目录读取静态信息，不加载 entry point。"""
    content = distribution(name).read_text("extra_metadata/plugin.meta.json")
    if content is None:
        raise FileNotFoundError(f"发行包 {name} 未包含 plugin.meta.json")
    return json.loads(content)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("generate", help="生成指定发行包或工作区的全部清单")
    build.add_argument("root", type=Path, nargs="?", default=Path.cwd())
    build.add_argument("--check", action="store_true")
    query = commands.add_parser("catalog", help="读取已安装发行包的静态目录")
    query.add_argument("distribution")
    args = parser.parse_args()
    if args.command == "catalog":
        print(json.dumps(read_catalog(args.distribution), ensure_ascii=False, indent=2))
        return
    root = args.root.resolve()
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    if "aurora-meta-build" in project.get("tool", {}):
        generate(root, check=args.check)
    else:
        for pattern in project["tool"]["uv"]["workspace"]["members"]:
            for member in root.glob(pattern):
                data = tomllib.loads((member / "pyproject.toml").read_text(encoding="utf-8"))
                if "aurora-meta-build" in data.get("tool", {}):
                    generate(member, check=args.check)
