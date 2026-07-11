# CLI 指南

## 文件结构

```
scripts/cli/
  main.py      # 入口：导入模块、调用 register()、match 分发
  utils.py     # 共享工具：run()、rich Console、PROJECT_ROOT
  check.py     # check 子命令
  runtime.py   # serve / console / default 子命令
```

## 模块契约

每个子命令模块须导出两个接口：

| 函数            | 签名                              | 职责                                        |
| --------------- | --------------------------------- | ------------------------------------------- |
| `register(sub)` | `sub: Any -> None`                | 通过 `sub.add_parser(...)` 注册自身及其参数 |
| `命令名(args)`  | `args: argparse.Namespace -> int` | 执行命令，返回退出码（0 成功）              |

- 函数名与子命令名**严格一致**（如 `check` 对应 `uv run aurora check`），main 的 `match` case 才能自动对等。
- 如果 `from __future__ import annotations` 生效，`argparse` 仅用于类型注解，应放在 `TYPE_CHECKING` 块内。

## 共享工具 (`utils.py`)

```python
from scripts.cli.utils import PROJECT_ROOT, console, run

# run(cmd) — 在 PROJECT_ROOT 下执行命令，打印状态，返回退出码
rc = run(["uv", "run", "pytest", "-v"])

# console.print(...) — rich Console，支持 [bold cyan] markup
console.print("[bold green]Done[/bold green]")
```

## 新增子命令

以新增 `aurora build` 为例：

### 1. 创建模块

`scripts/cli/build.py`：

```python
"""build 子命令。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import argparse

from scripts.cli.utils import console, run


def register(sub: Any) -> None:
    parser = sub.add_parser("build", help="构建项目")
    parser.add_argument("--release", action="store_true", help="发布模式")


def build(args: argparse.Namespace) -> int:
    mode = "release" if args.release else "debug"
    console.print(f"[bold]构建模式: {mode}[/bold]")
    return run(["uv", "run", "some-build-command", f"--mode={mode}"])
```

### 2. 在 main.py 中注册

```python
from scripts.cli import build, check, runtime  # 新增 import

def main() -> None:
    ...
    build.register(sub)  # 新增这行
    ...
```

### 3. 在 main.py 中分发

```python
match args.command:
    ...
    case "build":             # 新增 case
        sys.exit(build.build(args))  # module.函数名(args)
```

三步完成，main 不需要知道 `build` 的内部参数。
