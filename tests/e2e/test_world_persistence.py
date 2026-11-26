"""验证 world 的分发边界与宿主控制的最终落盘。"""

import asyncio
import json
import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import pytest
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context, StateKey
from aurora_core.discovery import load_plugins, register_plugins
from aurora_core.persistence import ContextPersistence
from aurora_core.snapshots import JsonSnapshotStore
from aurora_core.storage import StorageService
from aurora_world import RECORDS, SOURCES, WorldRecords


def environment(path):
    registry = bootstrap()
    register_plugins(registry, load_plugins(enabled=["aurora_world"]))
    ctx = Context(registry)
    store = JsonSnapshotStore(path)
    return ctx, store, ContextPersistence(ctx, store, interval=60)


def test_receipt_precedes_flush_and_failed_flush_preserves_retryable_records(tmp_path, monkeypatch):
    async def scenario():
        path = tmp_path / "world.json"
        ctx, store, persistence = environment(path)
        await persistence.start()
        storage = StorageService(tmp_path / "data")
        records = WorldRecords(ctx, storage)
        records.open()
        receipt = records.append(source_id="source", message_id="1", payload="原文")
        assert store.load() == ()
        save = store.save

        def fail(snapshot):
            raise OSError("磁盘不可写")

        monkeypatch.setattr(store, "save", fail)
        try:
            with pytest.raises(OSError, match="磁盘不可写"):
                await persistence.flush()
            assert store.load() == ()
            assert records.get(source_id="source", message_id="1") == receipt.record
            assert records.append(source_id="source", message_id="1", payload="原文").duplicate
            monkeypatch.setattr(store, "save", save)
            await persistence.flush()
            assert store.load()[0].address.key == RECORDS
        finally:
            monkeypatch.setattr(store, "save", save)
            await persistence.close()
            ctx.close()

        records.close()
        ctx, _, persistence = environment(path)
        observed = []
        handle = ctx.subscribe(observed.append, key=RECORDS, location={})
        try:
            await persistence.start()
            restored = WorldRecords(ctx, storage)
            restored.open()
            assert restored.read() == (receipt.record,)
            assert restored.read(after=receipt.record.position) == ()
            assert observed == []
            assert restored.append(source_id="source", message_id="1", payload="原文").duplicate
            assert observed == []
            new = restored.append(source_id="source", message_id="2", payload="后续输入")
            assert new.record.position.sequence == 2
            assert len(observed) == 1
        finally:
            restored.close()
            storage.close()
            ctx.unsubscribe(handle)
            await persistence.close()
            ctx.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("configured", [False, True])
def test_world_runs_and_restores_without_execution_or_host_packages(tmp_path, configured):
    launcher = """
import importlib.abc
import runpy
import sys

blocked = {'aurora_agent', 'aurora_bot', 'aurora_control', 'aurora_adapter',
           'aurora_cli', 'aurora_api', 'aurora_config'}

class AbsentPackages(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in blocked:
            raise ModuleNotFoundError('独立 world 环境不提供：' + fullname)

sys.meta_path.insert(0, AbsentPackages())
source = sys.argv.pop(1)
runpy.run_path(source, run_name='__main__')
assert not blocked.intersection(name.split('.')[0] for name in sys.modules)
"""
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "world_roundtrip.py"
    if configured:
        launcher = launcher.replace(", 'aurora_config'", "")
    results = []
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "-c", launcher, str(fixture), str(tmp_path), *(["--configured"] if configured else [])],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            timeout=15,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        results.append(json.loads(result.stdout))
    first, restored = results
    assert first["duplicate"] is False and restored["duplicate"] is True
    assert first["journal_id"] == restored["journal_id"]
    assert first["first_id"] == restored["first_id"]
    assert first["sequences"] == [1, 2] and restored["sequences"] == [1, 2, 3]


def test_world_distribution_owns_records_sources_and_lifecycle_definitions():
    assert metadata.requires("aurora-world") == [
        "aurora-core>=0.1.0",
        "aurora-config>=0.1.0; extra == 'config'",
        "aurora-config>=0.1.0; extra == 'environment'",
        "httpx<1,>=0.28; extra == 'environment'",
    ]
    plugin = load_plugins(enabled=["aurora_world"])[0]
    assert plugin.requires == ()
    entries = {entry.id: entry for entry in plugin.entries}
    assert all(
        entry.id.namespace == "org.aurora.world" and entry.provider == "aurora_world" for entry in entries.values()
    )
    assert entries[SOURCES].kind == "registry"
    assert {str(entry.id) for entry in entries.values() if entry.kind == "hook_handler"} == {
        f"org.aurora.world:handlers/{owner}/{phase}"
        for owner in ("sources", "records")
        for phase in ("prepare", "start", "stop", "clean")
    }
    entry = entries[RECORDS]
    assert entry.kind == "state_key"
    assert isinstance(entry.target, StateKey) and entry.target.persistent
