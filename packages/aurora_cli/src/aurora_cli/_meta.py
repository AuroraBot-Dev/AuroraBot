"""由 aurora-meta 生成；宿主公共声明的来源为 plugin.meta.toml。"""

from aurora_core.components import Definition
from aurora_core.ids import Id

COMMANDS = Id("org.aurora.cli:registries/commands")
COMMAND_SCHEMA = Id("org.aurora.cli:schemas/command")
CONFIGURATION = Id("org.aurora.cli:configs/default")
CONFIG = Id("org.aurora.cli:state/config")
CMD_ABOUT = Id("org.aurora.cli:commands/about")
CMD_CHECK = Id("org.aurora.cli:commands/check")
CMD_CTX_GET = Id("org.aurora.cli:commands/ctx/get")
CMD_CTX_SET = Id("org.aurora.cli:commands/ctx/set")
CMD_CTX_DELETE = Id("org.aurora.cli:commands/ctx/delete")
CMD_CTX_LIST = Id("org.aurora.cli:commands/ctx/list")
CMD_CTX_WATCH = Id("org.aurora.cli:commands/ctx/watch")
CMD_DONK_SHOW = Id("org.aurora.cli:commands/donk/show")
CMD_DONK_MAJOR = Id("org.aurora.cli:commands/donk/major")
CMD_DONK_MINOR = Id("org.aurora.cli:commands/donk/minor")
CMD_DONK_PATCH = Id("org.aurora.cli:commands/donk/patch")
CMD_HELP = Id("org.aurora.cli:commands/help")
CMD_ID_LIST = Id("org.aurora.cli:commands/id/list")
CMD_BOT = Id("org.aurora.cli:commands/bot")
CMD_PANEL = Id("org.aurora.cli:commands/panel")
CMD_TUI = Id("org.aurora.cli:commands/tui")
CMD_RUN = Id("org.aurora.cli:commands/run")
CMD_SERVE = Id("org.aurora.cli:commands/serve")

HOST_DEFINITIONS = {
    COMMANDS: Definition(COMMANDS, "registry", "aurora_cli", register_to=Id("org.aurora.core:registries/registries")),
    COMMAND_SCHEMA: Definition(
        COMMAND_SCHEMA, "schema", "aurora_cli", register_to=Id("org.aurora.core:registries/schemas")
    ),
    CONFIGURATION: Definition(
        CONFIGURATION, "config", "aurora_cli", register_to=Id("org.aurora.config:registries/configs")
    ),
    CONFIG: Definition(CONFIG, "state_key", "aurora_cli", register_to=Id("org.aurora.core:registries/state_keys")),
    CMD_ABOUT: Definition(
        CMD_ABOUT, "command", "aurora_cli.commands.about", register_to=Id("org.aurora.cli:registries/commands")
    ),
    CMD_CHECK: Definition(
        CMD_CHECK, "command", "aurora_cli.commands.check", register_to=Id("org.aurora.cli:registries/commands")
    ),
    CMD_CTX_GET: Definition(
        CMD_CTX_GET, "command", "aurora_cli.commands.ctx", register_to=Id("org.aurora.cli:registries/commands")
    ),
    CMD_CTX_SET: Definition(
        CMD_CTX_SET, "command", "aurora_cli.commands.ctx", register_to=Id("org.aurora.cli:registries/commands")
    ),
    CMD_CTX_DELETE: Definition(
        CMD_CTX_DELETE, "command", "aurora_cli.commands.ctx", register_to=Id("org.aurora.cli:registries/commands")
    ),
    CMD_CTX_LIST: Definition(
        CMD_CTX_LIST, "command", "aurora_cli.commands.ctx", register_to=Id("org.aurora.cli:registries/commands")
    ),
    CMD_CTX_WATCH: Definition(
        CMD_CTX_WATCH, "command", "aurora_cli.commands.ctx", register_to=Id("org.aurora.cli:registries/commands")
    ),
    CMD_DONK_SHOW: Definition(
        CMD_DONK_SHOW, "command", "aurora_cli.commands.donk", register_to=Id("org.aurora.cli:registries/commands")
    ),
    CMD_DONK_MAJOR: Definition(
        CMD_DONK_MAJOR, "command", "aurora_cli.commands.donk", register_to=Id("org.aurora.cli:registries/commands")
    ),
    CMD_DONK_MINOR: Definition(
        CMD_DONK_MINOR, "command", "aurora_cli.commands.donk", register_to=Id("org.aurora.cli:registries/commands")
    ),
    CMD_DONK_PATCH: Definition(
        CMD_DONK_PATCH, "command", "aurora_cli.commands.donk", register_to=Id("org.aurora.cli:registries/commands")
    ),
    CMD_HELP: Definition(
        CMD_HELP, "command", "aurora_cli.commands.help", register_to=Id("org.aurora.cli:registries/commands")
    ),
    CMD_ID_LIST: Definition(
        CMD_ID_LIST, "command", "aurora_cli.commands.id", register_to=Id("org.aurora.cli:registries/commands")
    ),
    CMD_BOT: Definition(
        CMD_BOT, "command", "aurora_cli.commands.launch", register_to=Id("org.aurora.cli:registries/commands")
    ),
    CMD_PANEL: Definition(
        CMD_PANEL, "command", "aurora_cli.commands.launch", register_to=Id("org.aurora.cli:registries/commands")
    ),
    CMD_TUI: Definition(
        CMD_TUI, "command", "aurora_cli.commands.launch", register_to=Id("org.aurora.cli:registries/commands")
    ),
    CMD_RUN: Definition(
        CMD_RUN, "command", "aurora_cli.commands.run", register_to=Id("org.aurora.cli:registries/commands")
    ),
    CMD_SERVE: Definition(
        CMD_SERVE, "command", "aurora_cli.commands.serve", register_to=Id("org.aurora.cli:registries/commands")
    ),
}
