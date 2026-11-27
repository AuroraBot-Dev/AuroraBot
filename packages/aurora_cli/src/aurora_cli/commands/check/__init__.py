"""将代码质量检查交给工作区的 TypeScript 脚本。"""

from pathlib import Path
from typing import TextIO

from ...declarations import CommandContext, builtin_commands
from ...utils.process import run_process

FLAGS = ("lint", "test", "full", "coverage", "fix", "unsafe_fixes", "check")


def execute(root: Path, output: TextIO, **options: object) -> int:
    if not (root / "scripts" / "check.ts").is_file() or not (root / "package.json").is_file():
        raise ValueError("项目根目录缺少 scripts/check.ts 或 package.json，请指定 --root")
    flags = [f"--{name.replace('_', '-')}" for name in FLAGS if options.get(name)]
    return run_process(["pnpm", "run", "check", *flags], root=root, output=output)


def dispatch(context: CommandContext, **options: object) -> int:
    return execute(context.root, context.output, **options)


def plugin():
    return builtin_commands(__name__, {"check": dispatch})
