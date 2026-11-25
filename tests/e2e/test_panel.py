"""Panel 观察模型通过共享客户端完成真实默认装配的工具往返。"""

import asyncio
import json
import os
from pathlib import Path

from aurora_api.access import AccessPolicy
from aurora_api.server import serve
from aurora_bot.assembly_config import AGENTS, MESSAGES, RUN, WORK
from aurora_bot.conversation import CONVERSATION
from aurora_core import entry_from
from test_default_assembly import seed, setup

ROOT = Path(__file__).resolve().parents[2]


def test_panel_observes_tool_results_and_confirms_completion(tmp_path):
    async def scenario():
        host, _, ctx, registry, _, _, events, _ = setup(tmp_path)
        registry.register_many(
            entry_from(target, provider="test") for target in (ctx.get, ctx.list, ctx.subscribe, ctx.unsubscribe)
        )
        process = None
        token = "test-panel-runtime-token-1234567890"
        await host.start(configure=lambda: seed(ctx))
        try:
            async with serve(
                registry,
                keys=[],
                read_only_keys=[AGENTS, MESSAGES, RUN, WORK],
                endpoints=[CONVERSATION],
                port=0,
                access=AccessPolicy(token=token),
            ) as url:
                process = await asyncio.create_subprocess_exec(
                    "node",
                    str(ROOT / "apps/aurora_panel/tests/live-process.ts"),
                    url,
                    cwd=ROOT,
                    env={**os.environ, "AURORA_TEST_ACCESS": token},
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                output, errors = await asyncio.wait_for(process.communicate(), 15)
                assert process.returncode == 0, errors.decode("utf-8")
                assert json.loads(output) == {"event": "complete"}
                assert events.count("tool.executed") == 1
                assert "tool.cancelled" not in events
        finally:
            if process is not None and process.returncode is None:
                process.kill()
                await process.communicate()
            await host.stop()

    asyncio.run(scenario())
