---
order: 7
---

# 外部工具位置（设计说明）

状态：草案（未实施）

本页是具体特性设计说明，不是设计思想。

## 动机

当前 setup、check、docs、panel、donk 等命令通过 `shutil.which` / `command -v` 在 PATH 中解析 git、uv、pnpm 等外部工具（`aurora/utils/process.py`、`aurora/commands/setup.py`、`aurora/utils/pnpm.py`）。这要求这些工具预先安装并暴露在 PATH 中。

未来会引入启动器：在软件内部携带并维护独立的 python/uv/pnpm/git，供项目引导与运行使用。启动器不能依赖系统的 PATH，因此外部工具的位置必须可以被显式指定。

## 设计

采用配置 + 环境变量双通道，未指定时回退 PATH：

1. **配置**：`config/runtime.toml` 新增 `[runtime.tools]` 段，为可选字段：`git`、`uv`、`pnpm`、`python`。值是可执行文件路径（绝对路径或相对路径）。
2. **环境变量**：`AURORA_GIT_PATH`、`AURORA_UV_PATH`、`AURORA_PNPM_PATH`、`AURORA_PYTHON_PATH` 作为兜底，供启动器在尚未写入个人配置时注入内部工具位置。
3. **解析顺序**：显式配置 → 环境变量 → PATH 查找。解析结果只在该次进程运行中使用，不写回配置。
4. **统一解析入口**：`aurora/utils/process.py` 提供 `resolve_tool(name)`，`run_process` 与 `aurora/utils/pnpm.py`、`aurora/commands/setup.py` 改用它；工具路径仅在进程启动时读取一次。

## 影响面

- `aurora/configs/runtime.py`：解析 `[runtime.tools]`。
- `aurora/utils/process.py`：`resolve_tool` 与 `run_process` 改造。
- `aurora/utils/pnpm.py`、`aurora/commands/setup.py`、`aurora/commands/check.py`、`aurora/commands/donk.py`：改用统一解析。
- `scripts/{linux,macos,windows}/setup.*`：前置检查改用解析结果；接收可选工具路径参数或环境变量。
- 测试：离线 fake 工具路径，不依赖真实安装。

## 明确不做的

- 不为非工具进程（如 pnpm 脚本透传的子命令）定义工具概念。
- 不提供配置界面或运行期热修改；工具位置是进程启动期只读事实。
