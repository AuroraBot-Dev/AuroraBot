"""验证原生终端、共享客户端和真实 bot 运行之间的动作关联。"""

import asyncio
import json
import os
from pathlib import Path

import pytest
from aurora_api.access import AccessPolicy
from aurora_api.server import serve
from aurora_bot.assembly_config import AGENTS, MESSAGES, RUN, WORK
from aurora_bot.conversation import CONVERSATION
from aurora_config import CONFIGURATION
from aurora_core import entry_from
from test_default_assembly import seed, setup

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("authenticated", [False, True])
def test_native_tui_submit_append_detach_and_cancel(tmp_path, authenticated):
    async def scenario():
        host, _, ctx, registry, _, _, events, _ = setup(tmp_path, behavior="wait")
        registry.register_many(
            entry_from(target, provider="test")
            for target in (ctx.get, ctx.set, ctx.delete, ctx.list, ctx.subscribe, ctx.unsubscribe)
        )
        process = None
        await host.start(configure=lambda: seed(ctx))
        token = "test-tui-access-token-123456789012" if authenticated else None
        try:
            async with serve(
                registry,
                keys=[AGENTS, MESSAGES, RUN, WORK],
                endpoints=[CONVERSATION, CONFIGURATION],
                port=0,
                access=AccessPolicy(token=token),
            ) as url:
                process = await asyncio.create_subprocess_exec(
                    "node",
                    "--experimental-ffi",
                    str(ROOT / "apps/aurora_tui/tests/live-process.ts"),
                    url,
                    cwd=ROOT,
                    env={**os.environ, "AURORA_TEST_ACCESS": token or ""},
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                output, errors = await asyncio.wait_for(process.communicate(), timeout=30)
                assert process.returncode == 0, errors.decode("utf-8") + output.decode("utf-8")
                assert json.loads(output.decode("utf-8").splitlines()[-1]) == {"event": "complete"}
                assert events.count("tool.executed") == 1
                assert events.count("tool.cancelled") == 1
                assert "tool.closed" not in events
        finally:
            if process is not None and process.returncode is None:
                process.kill()
                await process.communicate()
            await host.stop()
        assert events.index("tool.cancelled") < events.index("tool.closed") < events.index("model.closed")

    asyncio.run(scenario())
