"""AuroraBot 热重载 —— 保持 QQ/NoneBot 连接存活，仅重启脑回路。

触发方式：开发者在 QQ 发送 ``~reload`` 或 ``热重载``。
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
from typing import TYPE_CHECKING

from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.brain.kernel.circuit import Circuit
    from src.platform.application_host import ApplicationHost

logger = get_logger("HotReload")

_MODULES_TO_RELOAD = [
    "src.utils.json_utils",
    "src.brain.ai.llm_gate",
    "src.brain.prompts",
    "src.brain.kernel.base",
    "src.brain.kernel.state_store",
    "src.brain.nodes.agents.polaris_agent",
    "src.brain.nodes.agents",
    "src.brain.nodes",
    "src.brain.kernel.node_factory",
]


def _reload_modules() -> None:
    for name in _MODULES_TO_RELOAD:
        try:
            module = importlib.import_module(name)
            importlib.reload(module)
            logger.info("已重载模块 %s", name)
        except Exception:
            logger.exception("重载模块 %s 失败", name)


async def reload_brain(
    *,
    host: ApplicationHost,
    circuit: Circuit | None,
    bridge_task: asyncio.Task[None] | None,
    stop_event: asyncio.Event,
) -> tuple[Circuit | None, asyncio.Task[None] | None]:
    """热重载脑回路：停止 → 重载模块 → 重建 → 重启。

    Parameters
    ----------
    host : ApplicationHost
        应用宿主（不重启，QQ 连接存活）。
    circuit : Circuit | None
        当前电路实例。
    bridge_task : asyncio.Task | None
        当前事件桥接任务。
    stop_event : asyncio.Event
        停止信号事件。

    Returns
    -------
    tuple[Circuit | None, asyncio.Task | None]
        新的 (circuit, bridge_task)。
    """
    from src.brain.kernel.node_factory import build_circuit
    from src.brain.nodes import run_event_bridge
    from src.config import Config

    logger.info("热重载开始 — 停止脑回路...")

    # 1) 停止事件桥接
    if bridge_task is not None and not bridge_task.done():
        bridge_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bridge_task

    # 2) 停止电路
    if circuit is not None and circuit.is_running:
        await circuit.stop()

    # 3) 重载 Python 模块
    _reload_modules()

    # 4) 重建电路
    new_circuit = build_circuit(host)
    await new_circuit.start()

    # 5) 重启事件桥接
    new_bridge = asyncio.create_task(
        run_event_bridge(
            host,
            new_circuit,
            stop_event,
            interval=Config.HEARTBEAT_INTERVAL,
        )
    )

    logger.info("热重载完成")
    return new_circuit, new_bridge
