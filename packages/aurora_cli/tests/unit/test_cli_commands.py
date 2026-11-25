"""验证 CLI 接收普通数据声明、参数转换及订阅释放。"""

import asyncio
from dataclasses import replace
from io import StringIO

import pytest
from aurora_cli.commands.ctx.watch import watch
from aurora_cli.declarations import COMMANDS, CommandReceiver, read_command
from aurora_cli.parsing import command_parser
from aurora_core import Id
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import StateKey, install_context
from aurora_core.registry import RegistryEntry


def command(spec):
    return RegistryEntry(Id("dev.test:commands/echo"), "command", spec, "测试插件", register_to=COMMANDS)


def test_plain_command_description_converts_arguments():
    entry = command(
        {
            "help": "提交数据",
            "operation": "dev.test:operations/echo",
            "arguments": [
                {"name": "payload", "type": "json"},
                {"name": "count", "type": "integer", "option": True},
            ],
        }
    )
    assert CommandReceiver().rejection_reason(entry) is None
    parser = command_parser(read_command(entry))
    assert vars(parser.parse_args(['{"value": 3}', "--count", "2"])) == {"payload": {"value": 3}, "count": 2}
    assert vars(parser.parse_args(["null"])) == {"payload": None}
    for args in (["NaN"], ['{"a":1,"a":2}'], ["null", "--count", "x"], ["null", "--unknown"]):
        with pytest.raises(SystemExit) as caught:
            parser.parse_args(args)
        assert caught.value.code == 2


@pytest.mark.parametrize(
    "spec",
    [
        {"help": "缺少操作"},
        {"help": "重复绑定", "operation": "dev.test:operations/echo", "executor": lambda context: None},
        {"help": "装配参数缺失", "executor": lambda context: None, "runtime": True, "assembly_argument": "missing"},
        {"help": "重复参数", "operation": "dev.test:operations/echo", "arguments": [{"name": "x"}, {"name": "x"}]},
        {"help": "未知类型", "operation": "dev.test:operations/echo", "arguments": [{"name": "x", "type": "file"}]},
    ],
)
def test_incompatible_command_is_rejected(spec):
    assert CommandReceiver().rejection_reason(command(spec)) is not None


@pytest.mark.parametrize("output_fails", [False, True])
def test_watch_releases_subscription_on_cancel_or_output_failure(output_fails):
    async def scenario():
        registry = bootstrap()
        key = Id("dev.test:state/value")
        registry.register(RegistryEntry(key, "state_key", StateKey(), "测试插件"))
        ctx = install_context(registry)
        cancelled = []
        entry = registry.get(Id("org.aurora.core:operations/ctx/unsubscribe"))

        def unsubscribe(handle):
            cancelled.append(ctx.unsubscribe(handle))

        registry.replace(replace(entry, target=unsubscribe))

        class Output(StringIO):
            def write(self, value):
                if output_fails:
                    raise OSError("输出失败")
                return super().write(value)

        output = Output()
        task = asyncio.create_task(watch(registry, output, key=key, location={"scope": "one"}))
        await asyncio.sleep(0)
        ctx.set(key, "ignored")
        ctx.set(key, "seen", location={"scope": "one"})
        await asyncio.sleep(0)
        if output_fails:
            with pytest.raises(OSError, match="输出失败"):
                await task
        else:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert '"value": "seen"' in output.getvalue()
            assert "ignored" not in output.getvalue()
        assert cancelled == [True]
        ctx.close()

    asyncio.run(scenario())
