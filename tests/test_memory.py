"""memory 内存模块测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.memory import UnifiedMemoryManager, get_memory_manager
from src.memory.base import MemoryContext, MemoryItem
from src.memory.episodic import EpisodicMemory
from src.memory.semantic import SemanticMemory
from src.memory.working import WorkingMemory

# ═══════════════════════════════════════════════════════════════
# MemoryItem
# ═══════════════════════════════════════════════════════════════


class MemoryItemTest(unittest.TestCase):
    def test_default_fields(self) -> None:
        item = MemoryItem(content="hello")
        self.assertEqual(item.content, "hello")
        self.assertEqual(item.role, "user")
        self.assertIsInstance(item.timestamp, str)
        self.assertGreater(len(item.timestamp), 0)
        self.assertEqual(item.metadata, {})

    def test_custom_role_and_metadata(self) -> None:
        item = MemoryItem(
            content="reply",
            role="assistant",
            metadata={"source": "test"},
        )
        self.assertEqual(item.role, "assistant")
        self.assertEqual(item.metadata, {"source": "test"})

    def test_explicit_timestamp(self) -> None:
        item = MemoryItem(content="ts", timestamp="2026-01-01T00:00:00")
        self.assertEqual(item.timestamp, "2026-01-01T00:00:00")


# ═══════════════════════════════════════════════════════════════
# MemoryContext
# ═══════════════════════════════════════════════════════════════


class MemoryContextTest(unittest.TestCase):
    def test_empty_context_returns_empty_string(self) -> None:
        ctx = MemoryContext()
        self.assertEqual(ctx.to_prompt_text(), "")

    def test_working_context_only(self) -> None:
        ctx = MemoryContext(
            working_context=[
                MemoryItem(content="hello", role="user"),
                MemoryItem(content="hi there", role="assistant"),
            ],
        )
        text = ctx.to_prompt_text()
        self.assertIn("[当前上下文]", text)
        self.assertIn("- user: hello", text)
        self.assertIn("- assistant: hi there", text)

    def test_episodic_events_only(self) -> None:
        ctx = MemoryContext(
            episodic_events=[
                "[2026-01-01] chat_user: hello",
                "[2026-01-01] chat_assistant: hi",
            ],
        )
        text = ctx.to_prompt_text()
        self.assertIn("[相关历史事件]", text)
        self.assertIn("chat_user: hello", text)

    def test_semantic_facts_only(self) -> None:
        ctx = MemoryContext(
            semantic_facts=["用户喜欢 Python", "用户住在北京"],
        )
        text = ctx.to_prompt_text()
        self.assertIn("[已知事实与偏好]", text)
        self.assertIn("用户喜欢 Python", text)

    def test_all_three_layers(self) -> None:
        ctx = MemoryContext(
            working_context=[MemoryItem(content="最近消息", role="user")],
            episodic_events=["[2026-01-01] system: boot"],
            semantic_facts=["偏好: 简洁回复"],
        )
        text = ctx.to_prompt_text()
        self.assertIn("[当前上下文]", text)
        self.assertIn("[相关历史事件]", text)
        self.assertIn("[已知事实与偏好]", text)

    def test_empty_lists_excluded(self) -> None:
        ctx = MemoryContext(
            working_context=[],
            episodic_events=["[event]"],
            semantic_facts=[],
        )
        text = ctx.to_prompt_text()
        self.assertNotIn("[当前上下文]", text)
        self.assertIn("[相关历史事件]", text)
        self.assertNotIn("[已知事实与偏好]", text)


# ═══════════════════════════════════════════════════════════════
# WorkingMemory
# ═══════════════════════════════════════════════════════════════


class WorkingMemoryTest(unittest.TestCase):
    def test_add_and_get_context(self) -> None:
        wm = WorkingMemory(max_items=5)
        wm.add("hello", role="user")
        wm.add("hi", role="assistant")
        ctx = wm.get_context()
        self.assertEqual(len(ctx), 2)
        self.assertEqual(ctx[0].content, "hello")
        self.assertEqual(ctx[0].role, "user")
        self.assertEqual(ctx[1].content, "hi")
        self.assertEqual(ctx[1].role, "assistant")

    def test_capacity_limit_fifo(self) -> None:
        wm = WorkingMemory(max_items=3)
        for i in range(5):
            wm.add(f"msg_{i}")
        ctx = wm.get_context()
        self.assertEqual(len(ctx), 3)
        # Oldest two (msg_0, msg_1) evicted
        self.assertEqual(ctx[0].content, "msg_2")
        self.assertEqual(ctx[1].content, "msg_3")
        self.assertEqual(ctx[2].content, "msg_4")

    def test_clear_empties_store(self) -> None:
        wm = WorkingMemory(max_items=5)
        wm.add("keep")
        wm.clear()
        self.assertEqual(len(wm.get_context()), 0)

    def test_default_max_items(self) -> None:
        wm = WorkingMemory()
        self.assertEqual(wm.max_items, 10)


# ═══════════════════════════════════════════════════════════════
# EpisodicMemory
# ═══════════════════════════════════════════════════════════════


class EpisodicMemoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._tmp_path = Path(self._tmpdir.name) / "episodes.json"

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _make_instance(self) -> EpisodicMemory:
        mem = EpisodicMemory()
        mem._file_path = self._tmp_path
        return mem

    # ── record_event ──────────────────────────────────────

    def test_record_single_event(self) -> None:
        mem = self._make_instance()
        mem.record_event("chat_user", "hello world", user_id="u1")

        records = mem._load()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["type"], "chat_user")
        self.assertEqual(records[0]["content"], "hello world")
        self.assertEqual(records[0]["user_id"], "u1")
        self.assertIn("timestamp", records[0])

    def test_record_multiple_events_appends(self) -> None:
        mem = self._make_instance()
        mem.record_event("chat_user", "msg1", user_id="u1")
        mem.record_event("chat_assistant", "msg2", user_id="u1")
        self.assertEqual(len(mem._load()), 2)

    def test_dedup_skips_consecutive_duplicate(self) -> None:
        mem = self._make_instance()
        mem.record_event("chat_user", "same content", user_id="u1")
        mem.record_event("chat_user", "same content", user_id="u1")
        self.assertEqual(len(mem._load()), 1)

    def test_dedup_allows_same_content_different_user(self) -> None:
        mem = self._make_instance()
        mem.record_event("chat_user", "hi", user_id="u1")
        mem.record_event("chat_user", "hi", user_id="u2")
        self.assertEqual(len(mem._load()), 2)

    def test_dedup_allows_different_content_same_user(self) -> None:
        mem = self._make_instance()
        mem.record_event("chat_user", "hi", user_id="u1")
        mem.record_event("chat_user", "bye", user_id="u1")
        self.assertEqual(len(mem._load()), 2)

    # ── search_recent_events ──────────────────────────────

    def test_search_recent_returns_formatted_lines(self) -> None:
        mem = self._make_instance()
        mem.record_event("chat_user", "hello", user_id="u1")

        results = mem.search_recent_events(limit=5, user_id="u1")
        self.assertEqual(len(results), 1)
        self.assertIn("chat_user", results[0])
        self.assertIn("hello", results[0])

    def test_search_recent_respects_limit(self) -> None:
        mem = self._make_instance()
        for i in range(10):
            mem.record_event("chat_user", f"msg_{i}", user_id="u1")
        results = mem.search_recent_events(limit=3, user_id="u1")
        self.assertEqual(len(results), 3)
        self.assertIn("msg_9", results[-1])

    def test_search_recent_filters_by_user(self) -> None:
        mem = self._make_instance()
        mem.record_event("chat_user", "from_u1", user_id="u1")
        mem.record_event("chat_user", "from_u2", user_id="u2")

        results = mem.search_recent_events(limit=5, user_id="u1")
        self.assertEqual(len(results), 1)
        self.assertIn("from_u1", results[0])

    def test_search_recent_includes_summaries_for_all_users(self) -> None:
        mem = self._make_instance()
        # Simulate a compressed summary record
        summary = {
            "timestamp": "2026-01-01T00:00:00",
            "type": "summary",
            "user_id": "system",
            "content": "compressed summary",
        }
        mem._save([summary])
        mem.record_event("chat_user", "msg", user_id="u1")

        results = mem.search_recent_events(limit=5, user_id="u1")
        # Both the summary and the user event should appear
        self.assertGreaterEqual(len(results), 2)
        summary_found = any("compressed summary" in r for r in results)
        self.assertTrue(summary_found)

    # ── fold / compression ────────────────────────────────

    def test_fold_state_noop_when_few_records(self) -> None:
        """With threshold 5 and only 6 records, to_compress is empty → no fold."""
        mem = self._make_instance()
        mem._COMPRESS_THRESHOLD = 5

        for i in range(6):
            mem.record_event("chat_user", f"msg_{i}", user_id="u1")

        records = mem._load()
        # No fold: all 6 records preserved
        self.assertEqual(len(records), 6)

    def test_fold_state_triggers_with_enough_records(self) -> None:
        mem = self._make_instance()
        mem._COMPRESS_THRESHOLD = 5

        # Write 20 records: threshold 5 exceeded, to_compress = first 10,
        # to_keep = last 10 → 1 summary + 10 = 11 records
        for i in range(20):
            mem.record_event("chat_user", f"msg_{i}", user_id="u1")

        records = mem._load()
        self.assertEqual(len(records), 11)
        self.assertEqual(records[0]["type"], "summary")
        self.assertEqual(records[0]["user_id"], "system")
        self.assertIn("系统摘要", records[0]["content"])
        # Last 10 records should be the most recent messages
        self.assertEqual(len([r for r in records if r["type"] == "chat_user"]), 10)

    def test_fold_state_summary_content(self) -> None:
        mem = self._make_instance()
        mem._COMPRESS_THRESHOLD = 2

        for i in range(15):
            mem.record_event("chat_user", f"msg_{i}", user_id="u1")

        records = mem._load()
        summary = records[0]
        self.assertEqual(summary["type"], "summary")
        self.assertIn("次交互", summary["content"])

    # ── load/save robustness ─────────────────────────────

    def test_load_returns_empty_for_missing_file(self) -> None:
        mem = EpisodicMemory()
        mem._file_path = Path(tempfile.gettempdir()) / "nonexistent_episodes.json"
        self.assertEqual(mem._load(), [])

    def test_load_returns_empty_for_corrupted_file(self) -> None:
        self._tmp_path.parent.mkdir(parents=True, exist_ok=True)
        self._tmp_path.write_text("not valid json", encoding="utf-8")
        mem = self._make_instance()
        self.assertEqual(mem._load(), [])

    def test_save_and_load_roundtrip(self) -> None:
        mem = self._make_instance()
        data = [{"timestamp": "ts1", "type": "test", "user_id": "u1", "content": "c"}]
        mem._save(data)
        loaded = mem._load()
        self.assertEqual(loaded, data)

    # ── schedule_fold_refinement no event loop ────────────

    def test_schedule_fold_refinement_noop_when_no_event_loop(self) -> None:
        mem = self._make_instance()
        # No running event loop — should not raise
        mem._schedule_fold_refinement([], "", "", [])


# ═══════════════════════════════════════════════════════════
# UnifiedMemoryManager
# ═══════════════════════════════════════════════════════════


class UnifiedMemoryManagerTest(unittest.TestCase):
    def test_get_memory_manager_returns_singleton(self) -> None:
        first = get_memory_manager()
        second = get_memory_manager()
        self.assertIs(first, second)

    def test_process_interaction_writes_to_all_layers(self) -> None:
        mgr = UnifiedMemoryManager()

        with (
            patch.object(mgr.working, "add") as mock_wm_add,
            patch.object(mgr.episodic, "record_event") as mock_ep_record,
            patch.object(mgr, "_schedule_semantic_extract") as mock_sem_sched,
        ):
            mgr.process_interaction(content="hello world", role="user", user_id="u1")

        mock_wm_add.assert_called_once_with(content="hello world", role="user")
        mock_ep_record.assert_called_once_with(event_type="chat_user", content="hello world", user_id="u1")
        mock_sem_sched.assert_called_once_with("hello world", "u1")

    def test_process_interaction_schedules_semantic_only_for_user(self) -> None:
        mgr = UnifiedMemoryManager()

        with patch.object(mgr, "_schedule_semantic_extract") as mock_sem_sched:
            mgr.process_interaction(content="bot reply", role="assistant", user_id="u1")

        mock_sem_sched.assert_not_called()

    def test_retrieve_context_aggregates_all_layers(self) -> None:
        mgr = UnifiedMemoryManager()

        with (
            patch.object(
                mgr.working,
                "get_context",
                return_value=[MemoryItem(content="wm", role="user")],
            ),
            patch.object(
                mgr.episodic,
                "search_recent_events",
                return_value=["[ts] event: something"],
            ),
            patch.object(
                mgr.semantic,
                "search_facts",
                return_value=["fact: user likes cats"],
            ),
        ):
            ctx = mgr.retrieve_context(current_query="hello", user_id="u1")

        self.assertEqual(len(ctx.working_context), 1)
        self.assertEqual(len(ctx.episodic_events), 1)
        self.assertEqual(len(ctx.semantic_facts), 1)

    def test_retrieve_context_passes_user_id_to_sub_components(self) -> None:
        mgr = UnifiedMemoryManager()

        with (
            patch.object(mgr.episodic, "search_recent_events") as mock_ep,
            patch.object(mgr.semantic, "search_facts") as mock_sem,
        ):
            mgr.retrieve_context(current_query="q", user_id="specific_user")

        mock_ep.assert_called_once_with(limit=5, user_id="specific_user")
        mock_sem.assert_called_once_with(query="q", user_id="specific_user")

    def test_process_interaction_falls_back_to_default_user_id(self) -> None:
        mgr = UnifiedMemoryManager()
        # Empty user_id should use init_user_id fallback
        with patch.object(mgr.working, "add") as mock_add:
            mgr.process_interaction(content="test", role="user", user_id="")
        mock_add.assert_called_once_with(content="test", role="user")

    def test_schedule_semantic_extract_sync_fallback_on_no_loop(self) -> None:
        mgr = UnifiedMemoryManager()
        with patch.object(mgr.semantic, "extract_and_store") as mock_extract:
            mgr._schedule_semantic_extract("test text", "u1")
        mock_extract.assert_called_once_with(text="test text", user_id="u1")


class SemanticMemoryTest(unittest.TestCase):
    def test_extract_and_store_skips_when_credentials_missing(self) -> None:
        mem = SemanticMemory()
        with (
            patch.object(
                mem,
                "_missing_credentials_reason",
                return_value="未配置 OPENAI_API_KEY",
            ),
            patch("src.memory.semantic.logger.warning") as mock_warning,
        ):
            stored = mem.extract_and_store("hello", "u1")

        self.assertFalse(stored)
        mock_warning.assert_called_once()

    def test_search_facts_returns_empty_when_credentials_missing(self) -> None:
        mem = SemanticMemory()
        with (
            patch.object(
                mem,
                "_missing_credentials_reason",
                return_value="未配置 OPENAI_API_KEY",
            ),
            patch("src.memory.semantic.logger.warning") as mock_warning,
        ):
            results = mem.search_facts("hello", "u1")

        self.assertEqual(results, [])
        mock_warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
