"""停机后显式迁移旧 ctx 世界日志；保留原快照备份与已有消费身份。"""

import argparse
import os
from pathlib import Path
from time import time
from typing import cast

from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context, ContextSnapshot, StateRecord
from aurora_core.discovery import register_plugins
from aurora_core.storage import StorageService

from .legacy import validate_records
from .plugin import plugin
from .records import RECORDS, WorldRecords, _content


def migrate(root: Path) -> int:
    """导入保留日志后替换快照中的 world 项；数据库已提交但快照失败时可重试。"""
    with StorageService(root) as storage:
        store = storage.snapshot_store()
        snapshot = store.load()
        candidates = [item for item in snapshot if item.address.key == RECORDS]
        if not candidates:
            return 0
        if len(candidates) != 1 or candidates[0].address.location:
            raise ValueError("旧 world 日志必须使用唯一全局地址")
        old = cast(dict, candidates[0].value)
        if old.get("version") == 3:
            return 0
        validate_records(old)
        backup = store.path.with_name("ctx.before-world-database.json")
        if backup.exists() and backup.read_bytes() != store.path.read_bytes():
            raise ValueError("迁移备份已存在且内容不同，请先核对备份")
        if not backup.exists():
            with backup.open("xb") as output:
                output.write(store.path.read_bytes())
                output.flush()
                os.fsync(output.fileno())
        registry = bootstrap()
        register_plugins(registry, [plugin()])
        ctx = Context(registry)
        records = WorldRecords(ctx, storage)
        try:
            records.open()
            db = records._connection()
            journal = db.execute("SELECT * FROM journal").fetchone()
            next_sequence = old.get("next_sequence", len(old["records"]) + 1)
            if journal["next_sequence"] != 1 and (
                journal["id"] != old["journal_id"] or journal["next_sequence"] != next_sequence
            ):
                raise ValueError("目标数据库已有不同日志，拒绝覆盖")
            received = time()
            with db:
                for item in old["records"]:
                    encoded = _content(item["payload"])
                    existing = db.execute("SELECT * FROM events WHERE sequence=?", (item["sequence"],)).fetchone()
                    if existing is not None:
                        if (
                            any(existing[key] != item[key] for key in ("record_id", "source_id", "message_id"))
                            or existing["payload"] != encoded
                        ):
                            raise ValueError("迁移记录与目标数据库冲突")
                        continue
                    db.execute(
                        "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            item["sequence"],
                            item["record_id"],
                            item["source_id"],
                            item["message_id"],
                            received,
                            encoded,
                            item["payload"] if isinstance(item["payload"], str) else encoded,
                        ),
                    )
                db.execute(
                    "UPDATE journal SET id=?, next_sequence=?, pruned_through=?, pruned_record_id=?",
                    (old["journal_id"], next_sequence, old.get("pruned_through", 0), old.get("pruned_record_id")),
                )
            records.refresh()
            value = (
                ctx.get(RECORDS)
                if ctx.list(key=RECORDS)
                else {"version": 3, "journal_id": old["journal_id"], "latest_sequence": 0, "records": []}
            )
            updated = tuple(
                StateRecord(item.address, value) if item.address.key == RECORDS else item for item in snapshot
            )
            store.save(ContextSnapshot(0, updated))
            return len(old["records"])
        finally:
            records.close()
            ctx.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="停机后迁移 world 日志，保留原 ctx 快照备份")
    parser.add_argument("--root", type=Path, required=True, help="宿主数据目录，包含 framework/ctx.json")
    args = parser.parse_args()
    print(f"已迁移 {migrate(args.root)} 条世界事件；备份位于 framework/ctx.before-world-database.json")


if __name__ == "__main__":
    main()
