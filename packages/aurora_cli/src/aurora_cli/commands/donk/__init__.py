"""统一管理当前 Python 工作区版本；版本策略仅在本命令中定义。"""

import re
import shutil
import tomllib
from functools import partial
from pathlib import Path
from typing import Any, TextIO

import tomlkit

from ...declarations import CommandContext, command_plugin
from ...utils.process import run_process

DEFINITIONS = {
    f"donk/{name}": {"help": help_text}
    for name, help_text in (
        ("show", "显示 Python 工作区版本"),
        ("major", "升级主版本号"),
        ("minor", "升级次版本号"),
        ("patch", "升级修订版本号"),
    )
}


def _projects(root: Path) -> list[Path]:
    root = root.resolve()
    path = (root / "pyproject.toml").resolve()
    if not path.is_relative_to(root):
        raise ValueError("项目文件必须位于根目录内")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if data.get("project", {}).get("name") != "aurorabot-ai":
        raise ValueError("donk 需要 aurorabot-ai 工作区根目录，请指定 --root")
    workspace = data.get("tool", {}).get("uv", {}).get("workspace", {})
    paths = {path}
    excluded = {item.resolve() for pattern in workspace.get("exclude", []) for item in root.glob(pattern)}
    for pattern in workspace.get("members", []):
        members = list(root.glob(pattern))
        if not members:
            raise ValueError(f"工作区成员不存在：{pattern}")
        for member in members:
            member = member.resolve()
            if not member.is_relative_to(root):
                raise ValueError("工作区成员必须位于根目录内")
            if member not in excluded:
                project = (member / "pyproject.toml").resolve()
                if not project.is_relative_to(root):
                    raise ValueError("项目文件必须位于根目录内")
                paths.add(project)
    return sorted(paths)


def execute(action: str, root: Path, output: TextIO) -> int:
    paths = _projects(root)
    originals = {path: path.read_bytes() for path in paths}
    documents: dict[Path, Any] = {path: tomlkit.parse(content.decode("utf-8")) for path, content in originals.items()}
    versions = {str(document["project"]["version"]) for document in documents.values()}
    if action == "show":
        for document in documents.values():
            print(f"{document['project']['name']}: {document['project']['version']}", file=output)
        return 0
    if action not in ("major", "minor", "patch"):
        raise ValueError(f"未知版本动作：{action}")
    if len(versions) != 1:
        raise ValueError("当前统一版本策略要求所有 Python 包版本一致")
    current = versions.pop()
    if re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", current) is None:
        raise ValueError("统一版本升级仅接受 major.minor.patch 格式的正式版本")
    parts = [int(part) for part in current.split(".")]
    index = ("major", "minor", "patch").index(action)
    parts[index] += 1
    parts[index + 1 :] = [0] * (2 - index)
    updated = ".".join(map(str, parts))
    names = {document["project"]["name"] for document in documents.values()}
    for document in documents.values():
        project = document["project"]
        project["version"] = updated
        dependencies = project.get("dependencies", [])
        for position, dependency in enumerate(dependencies):
            match = re.match(r"([A-Za-z0-9_.-]+)", dependency)
            if match is not None and match[1] in names:
                constraint = dependency[len(match[1]) :]
                if constraint not in (f">={current}", f"=={current}"):
                    raise ValueError(f"内部依赖需使用当前版本的 >= 或 == 约束：{dependency}")
                dependencies[position] = f"{match[1]}{constraint[:2]}{updated}"
    if shutil.which("uv") is None:
        raise FileNotFoundError("找不到工具：uv")
    lock = root / "uv.lock"
    if lock.is_symlink():
        raise ValueError("uv.lock 不能为符号链接")
    previous_lock = lock.read_bytes() if lock.exists() else None
    try:
        for path, document in documents.items():
            path.write_text(tomlkit.dumps(document), encoding="utf-8", newline="")
        code = run_process(["uv", "lock"], root=root, output=output)
        if code:
            raise RuntimeError(f"uv lock 失败，退出码：{code}")
    except BaseException:
        for path, content in originals.items():
            path.write_bytes(content)
        if previous_lock is None:
            lock.unlink(missing_ok=True)
        else:
            lock.write_bytes(previous_lock)
        raise
    print(f"Python 工作区版本已更新为：{updated}", file=output)
    return 0


def dispatch(action: str, context: CommandContext) -> int:
    return execute(action, context.root, context.output)


def plugin():
    return command_plugin(
        __name__,
        {name: {**spec, "executor": partial(dispatch, name.split("/")[1])} for name, spec in DEFINITIONS.items()},
    )
