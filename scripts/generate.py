"""按需导出 ctx JSON 描述与 TypeScript 类型；--check 只检查产物是否过期。"""

import argparse
import json
import subprocess
from pathlib import Path

from aurora_api.contract import describe_contract
from aurora_bot.conversation_contract import describe_conversation
from aurora_config.editor_contract import describe_configuration

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "packages/aurora_client/src/generated"


def _type(schema: dict) -> str:
    if "$ref" in schema:
        return schema["$ref"].removeprefix("#/$defs/")
    if "const" in schema:
        if isinstance(schema["const"], bool):
            return str(schema["const"]).lower()
        return repr(schema["const"])
    if "enum" in schema:
        return " | ".join(sorted(repr(value) for value in schema["enum"]))
    if "anyOf" in schema:
        return " | ".join(sorted((_type(item) for item in schema["anyOf"]), key=str.casefold))
    kind = schema["type"]
    if kind == "array":
        return f"{_type(schema['items'])}[]"
    if kind == "object":
        if "properties" not in schema:
            return f"{{ [key: string]: {_type(schema['additionalProperties'])} }}"
        if not schema["properties"]:
            return "Record<string, never>"
        required = schema["required"]
        fields = [
            f"  {name}{'' if name in required else '?'}: {_type(value)};"
            for name, value in sorted(schema["properties"].items())
        ]
        return "{\n" + "\n".join(fields) + "\n}"
    return {"null": "null", "boolean": "boolean", "integer": "number", "number": "number", "string": "string"}[kind]


def render_typescript(contract: dict) -> str:
    """仅转换 ctx 描述使用的类型结构；字段约束由 JSON 描述和服务端校验保留。"""
    parts = ["// 由 scripts/generate.py 生成，来源为 aurora_api、aurora_bot 与 aurora_config 的显式传输契约。"]
    for name, schema in sorted(contract["$defs"].items()):
        parts.append(f"export type {name} = {_type(schema)};")
    for name, field in (("HttpRequests", "request"), ("HttpResponses", "response")):
        fields = "\n".join(
            f"  {action}: {_type(binding[field])};" for action, binding in sorted(contract["http"].items())
        )
        parts.append(f"export interface {name} {{\n{fields}\n}}")
    bindings = []
    for action, binding in sorted(contract["http"].items()):
        bindings.append(
            f"  {action}: {{\n"
            f"    method: '{binding['method']}',\n"
            f"    path: '{binding['path']}',\n"
            f"    operation: {repr(binding['operation']) if binding['operation'] else 'null'},\n"
            "  },"
        )
    parts.append("export const HTTP_BINDINGS = {\n" + "\n".join(bindings) + "\n} as const;")
    watch = contract["watch"]
    fields = "\n".join(f"  {name}: '{watch[name]}'," for name in ("path", "subscribe", "unsubscribe", "event"))
    parts.append("export const WATCH_BINDING = {\n" + fields + "\n} as const;")
    return "\n\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="不写文件，产物缺失或过期时返回非零")
    parser.add_argument("--output", type=Path, default=OUTPUT, help="产物目录")
    args = parser.parse_args()
    contract = describe_contract(extensions=[describe_conversation(), describe_configuration()])
    files = {
        "ctx-contract.json": json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
        "ctx-contract.ts": render_typescript(contract),
    }
    # 使用工作区固定的格式器，使生成结果与完整检查采用同一配置。
    formatter = """
import * as prettier from 'prettier';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const files = JSON.parse(input);
for (const [name, content] of Object.entries(files)) {
  const filepath = `packages/aurora_client/src/generated/${name}`;
  const options = await prettier.resolveConfig(filepath);
  files[name] = await prettier.format(content, { ...options, filepath });
}
process.stdout.write(JSON.stringify(files));
"""
    formatted = subprocess.run(
        ["node", "--input-type=module", "-e", formatter],
        input=json.dumps(files),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=30,
        check=True,
    )
    files = json.loads(formatted.stdout)
    outdated = []
    for name, content in files.items():
        path = args.output / name
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                outdated.append(str(path))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
    if outdated:
        print("ctx 契约产物缺失或过期：\n" + "\n".join(outdated))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
