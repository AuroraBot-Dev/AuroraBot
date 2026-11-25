"""验证宿主快照、结构化存储与插件自有数据库的组合。"""

import asyncio
import sqlite3

from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context, StateKey
from aurora_core.ids import Id
from aurora_core.persistence import ContextPersistence
from aurora_core.registry import RegistryEntry
from aurora_core.storage import StorageService

KEY = Id("dev.example:state/config")


def make_context() -> Context:
    registry = bootstrap()
    registry.register(RegistryEntry(KEY, "state_key", StateKey(), "测试插件"))
    return Context(registry)


def test_host_storage_and_plugin_database_are_independent(tmp_path):
    async def scenario():
        with StorageService(tmp_path) as storage:
            ctx = make_context()
            persistence = ContextPersistence(ctx, storage.snapshot_store())
            await persistence.start()
            ctx.set(KEY, {"model": "test"})
            storage.set("dev.example", "index", {"count": 1})
            plugin_path = storage.directory("dev.example") / "memory.sqlite3"
            plugin_database = sqlite3.connect(plugin_path)
            try:
                with plugin_database:
                    plugin_database.execute("CREATE TABLE memories (text TEXT)")
                    plugin_database.execute("INSERT INTO memories VALUES (?)", ("插件内容",))
                assert [record.address.key for record in ctx.snapshot().records] == [KEY]
                # 插件停止期间产生的最后状态修改须在存储释放前完成落盘。
                ctx.set(KEY, {"model": "final"})
            finally:
                plugin_database.close()
            await persistence.close()
        ctx.close()
        with StorageService(tmp_path) as storage:
            ctx = make_context()
            persistence = ContextPersistence(ctx, storage.snapshot_store())
            await persistence.start()
            assert ctx.get(KEY) == {"model": "final"}
            assert storage.get("dev.example", "index") == {"count": 1}
            plugin_database = sqlite3.connect(storage.directory("dev.example") / "memory.sqlite3")
            try:
                assert plugin_database.execute("SELECT text FROM memories").fetchone()[0] == "插件内容"
            finally:
                plugin_database.close()
            assert len(ctx.list()) == 1
            await persistence.close()
        ctx.close()

    asyncio.run(scenario())
