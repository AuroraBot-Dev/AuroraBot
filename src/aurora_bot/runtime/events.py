"""运行门面直接输入的世界事件与所属域。"""

from aurora_bot.contracts.identity import world_scope

RUNTIME_SCOPE = f"{world_scope('aurora')}/runtime"
RUNTIME_INPUT = "runtime.input"

RUNTIME_MODULE_FAILED = "runtime.module.failed"
