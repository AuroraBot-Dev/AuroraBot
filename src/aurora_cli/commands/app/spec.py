from __future__ import annotations

from typing import TYPE_CHECKING

from aurora_cli.commands.app.github import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ORDER_FIELDS,
    SORT_FIELDS,
    TOPIC_CLAUSE,
)

if TYPE_CHECKING:
    from aurora_cli.contracts.command import CommandSpec


COMMAND: CommandSpec = {
    "name": "app",
    "help": "查看并调整 MCP App 注册表",
    "subcommands": {
        "list": {"help": "列出 config/apps.toml 中的 App 及其就绪状态"},
        "search": {
            "help": "按 topic 搜索可安装的 App 仓库",
            "args": {
                "query": {
                    "nargs": "?",
                    "default": None,
                    "metavar": "QUERY",
                    "help": f"关键词，追加到 {TOPIC_CLAUSE} 之后",
                },
            },
            "options": {
                "--page": {"type": int, "default": DEFAULT_PAGE, "metavar": "N", "help": "页码，从 1 开始"},
                "--page-size": {
                    "type": int,
                    "default": DEFAULT_PAGE_SIZE,
                    "metavar": "N",
                    "help": f"每页条数，最多 {MAX_PAGE_SIZE}",
                },
                "--sort": {"metavar": "FIELD", "help": f"排序字段，可选 {'、'.join(SORT_FIELDS)}"},
                "--order": {"metavar": "ORDER", "help": f"排序方向，可选 {'、'.join(ORDER_FIELDS)}，需与 --sort 同用"},
            },
        },
        "install": {
            "help": "安装本地 MCP 包、登记已在运行的远程 MCP 端点，或安装声明了启动方式的源码仓库",
            "args": {
                "repository": {
                    "nargs": "?",
                    "default": None,
                    "metavar": "SOURCE",
                    "help": "远程 MCP 的 HTTPS URL，或源码仓库（owner/repo、GitHub HTTPS/SSH URL）",
                },
            },
            "options": {
                "--ref": {"metavar": "REF", "help": "分支或标签，交给 Git 解析，不预判形状"},
                "--package": {"metavar": "ID", "help": "显式 package ID，默认由来源推导"},
                "--auth-env": {
                    "metavar": "ENV_NAME",
                    "help": "远程 MCP 的 Bearer token 环境变量名；仅适用于 HTTPS URL",
                },
                "--command": {
                    "metavar": "JSON",
                    "help": "显式启动命令，JSON 字符串数组；给出后不再要求 aurora-app.toml",
                },
                "--npx": {"metavar": "PACKAGE", "help": "交给 npx 运行的包，不克隆任何仓库"},
                "--uvx": {"metavar": "PACKAGE", "help": "交给 uvx 运行的包，不克隆任何仓库"},
                "--arg": {
                    "action": "append",
                    "metavar": "VALUE",
                    "help": "传给 Server 的参数，可重复；排在包名之后（如允许访问的目录）",
                },
                "--events": {
                    "action": "store_true",
                    "help": "登记为世界生产者：只把 Server 上报的外部事实推进世界线，不要求它暴露 Tool",
                },
                "--disabled": {"action": "store_true", "help": "登记为禁用；默认启用"},
                "--yes": {"action": "store_true", "help": "跳过最终确认，不跳过任何检查"},
            },
        },
        "remove": {
            "help": "从注册表移除一个 App，受管安装目录一并删除",
            "args": {"package": "注册表中的小写点分 package ID"},
            "options": {"--force": {"action": "store_true", "help": "只跳过 origin 归属校验，不放宽路径边界"}},
        },
        "enable": {
            "help": "允许 App 在下次 aurora start 时启动",
            "args": {"package": "注册表中的小写点分 package ID"},
        },
        "disable": {
            "help": "禁止 App 在下次 aurora start 时启动",
            "args": {"package": "注册表中的小写点分 package ID"},
        },
    },
}
