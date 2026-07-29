"""终态 Task 的热库清理与 SQLite 空间维护。"""

from __future__ import annotations

from src.contracts.agent import TaskStatus

from .base import RuntimeStoreBase


class StoreRetentionMixin(RuntimeStoreBase):
    """归档成功后清除终态明细，同时保留外部消息幂等墓碑。"""

    def prune_archived_task(self, task_id: str) -> bool:
        with self.transaction() as connection:
            task = connection.execute("SELECT status FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if task is None or TaskStatus(task["status"]) == TaskStatus.ACTIVE:
                return False
            connection.execute(
                "DELETE FROM causal_events WHERE task_id = ? AND external_message_id IS NULL",
                (task_id,),
            )
            connection.execute(
                "UPDATE causal_events SET task_id = NULL, agent_id = NULL, summary = 'archived external receipt', "
                "payload_json = '{}', causation_id = NULL WHERE task_id = ? AND external_message_id IS NOT NULL",
                (task_id,),
            )
            connection.execute("DELETE FROM mailbox WHERE task_id = ?", (task_id,))
            connection.execute("DELETE FROM activities WHERE task_id = ?", (task_id,))
            connection.execute("DELETE FROM agents WHERE task_id = ?", (task_id,))
            connection.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
        return True

    def maintain_storage(self) -> None:
        """回收空闲页并限制 WAL 的稳定态尺寸。"""
        with self.connect() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
            free_pages = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
            if free_pages and free_pages * 2 >= page_count:
                connection.execute("VACUUM")
            elif free_pages:
                connection.execute(f"PRAGMA incremental_vacuum({min(free_pages, 256)})")
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
