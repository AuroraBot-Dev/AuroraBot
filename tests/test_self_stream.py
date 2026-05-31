"""SelfStream 单元测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.brain.nodes.self_stream import SelfStream


class SelfStreamInitTest(unittest.TestCase):
    """初始化 & 目录创建测试。"""

    def test_init_creates_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "self"
            s = SelfStream(base_dir=base)
            self.assertTrue(s.now_path.exists())
            self.assertTrue(s.state_path.exists())
            self.assertTrue((base / "stream" / "archive").is_dir())
            self.assertTrue((base / "memories").is_dir())
            self.assertTrue((base / "diary").is_dir())

    def test_init_creates_default_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            s = SelfStream(base_dir=Path(tmp))
            now = s.read_full()
            self.assertIn("就在刚刚", now)
            state = s.read_state()
            self.assertIn("自我状态", state)

    def test_init_does_not_overwrite_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            # 第一次创建
            s1 = SelfStream(base_dir=base)
            s1.append_experience("自定义内容")
            # 第二次创建——不覆盖
            s2 = SelfStream(base_dir=base)
            self.assertIn("自定义内容", s2.read_full())

    def test_default_base_dir(self) -> None:
        s = SelfStream()
        self.assertIn("kernel", str(s.now_path))
        self.assertIn("self", str(s.now_path))


class SelfStreamNowTest(unittest.TestCase):
    """now.md 读写测试。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.stream = SelfStream(base_dir=Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_append_experience_adds_content(self) -> None:
        self.stream.append_experience("Alice 说：你好。")
        full = self.stream.read_full()
        self.assertIn("Alice 说：你好", full)

    def test_append_experience_adds_timestamp(self) -> None:
        self.stream.append_experience("测试。")
        full = self.stream.read_full()
        self.assertIn("### 20", full)  # 时间戳以 "### 20xx-xx-xx" 开头

    def test_append_experience_returns_bytes_written(self) -> None:
        written = self.stream.append_experience("测试。")
        self.assertGreater(written, 0)

    def test_multiple_appends_are_sequential(self) -> None:
        self.stream.append_experience("第一条。")
        self.stream.append_experience("第二条。")
        full = self.stream.read_full()
        pos1 = full.index("第一条")
        pos2 = full.index("第二条")
        self.assertLess(pos1, pos2)

    def test_read_recent_last_n_lines(self) -> None:
        for i in range(20):
            self.stream.append_experience(f"第{i}条消息。")
        # 每条 append 产生约 4-5 行，读 60 行确保覆盖最后 ~12 条
        recent = self.stream.read_recent(60)
        self.assertIn("第19条消息", recent)
        self.assertIn("第15条消息", recent)
        self.assertNotIn("第0条消息", recent)

    def test_read_recent_n_zero(self) -> None:
        self.stream.append_experience("测试。")
        recent = self.stream.read_recent(0)
        self.assertEqual(recent, "")

    def test_read_recent_n_larger_than_file(self) -> None:
        self.stream.append_experience("只有一条。")
        recent = self.stream.read_recent(100)
        self.assertIn("只有一条", recent)

    def test_read_recent_chars_truncates(self) -> None:
        self.stream.append_experience("A" * 5000)
        chars = self.stream.read_recent_chars(200)
        self.assertLessEqual(len(chars), 200 + 50)  # 允许少许 overhead
        self.assertIn("(更早的内容已省略)", chars)

    def test_read_recent_chars_no_truncation_when_short(self) -> None:
        self.stream.append_experience("短内容。")
        chars = self.stream.read_recent_chars(4000)
        self.assertNotIn("(更早的内容已省略)", chars)

    def test_truncate_keeps_last_n_lines(self) -> None:
        for i in range(20):
            self.stream.append_experience(f"第{i}条。")
        # 每条 append ~5 行，读 12 行保留最后 2 条左右
        self.stream.truncate(keep_last_n_lines=12)
        full = self.stream.read_full()
        self.assertIn("第19条", full)
        self.assertIn("第18条", full)
        self.assertNotIn("第0条", full)

    def test_read_full_defaults_to_initial_on_error(self) -> None:
        # 删除 now.md 再读——应返回初始模板
        self.stream.now_path.unlink()
        full = self.stream.read_full()
        self.assertIn("就在刚刚", full)


class SelfStreamStateTest(unittest.TestCase):
    """state.md 读写测试。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.stream = SelfStream(base_dir=Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_read_state_returns_default(self) -> None:
        state = self.stream.read_state()
        self.assertIn("自我状态", state)

    def test_update_state_overwrites(self) -> None:
        self.stream.update_state("- 精力：高\n")
        self.assertEqual(self.stream.read_state(), "- 精力：高\n")

    def test_state_path_property(self) -> None:
        self.assertTrue(self.stream.state_path.name.endswith("state.md"))


class SelfStreamMemoryTest(unittest.TestCase):
    """memories/ 读写测试。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.stream = SelfStream(base_dir=Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_write_and_read_memory(self) -> None:
        self.stream.write_memory("alice", "Alice 喜欢古典音乐。")
        self.assertEqual(self.stream.read_memory("alice"), "Alice 喜欢古典音乐。")

    def test_read_nonexistent_memory(self) -> None:
        self.assertIsNone(self.stream.read_memory("nonexistent"))

    def test_list_memories(self) -> None:
        self.stream.write_memory("alice", "...")
        self.stream.write_memory("bob", "...")
        memories = self.stream.list_memories()
        self.assertIn("alice", memories)
        self.assertIn("bob", memories)

    def test_append_memory(self) -> None:
        self.stream.write_memory("notes", "第一行。\n")
        self.stream.append_memory("notes", "第二行。\n")
        content = self.stream.read_memory("notes")
        self.assertIn("第一行", content or "")
        self.assertIn("第二行", content or "")

    def test_memory_name_sanitization(self) -> None:
        self.stream.write_memory("a/b", "内容")
        self.assertIn("a_b", self.stream.list_memories())

    def test_list_memories_empty(self) -> None:
        self.assertEqual(self.stream.list_memories(), [])


class SelfStreamArchiveTest(unittest.TestCase):
    """归档测试。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.stream = SelfStream(base_dir=Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_archive_today_preserves_content(self) -> None:
        self.stream.append_experience("重要体验。")
        self.stream.archive_today("2025-03-15")
        archived = self.stream.read_archive("2025-03-15")
        self.assertIsNotNone(archived)
        self.assertIn("重要体验", archived or "")

    def test_archive_today_truncates_now(self) -> None:
        for i in range(30):
            self.stream.append_experience(f"消息{i}。")
        self.stream.archive_today("2025-03-15")
        now = self.stream.read_full()
        lines = now.splitlines()
        self.assertLess(len(lines), 20)  # 截断后应该很短

    def test_read_archive_nonexistent(self) -> None:
        self.assertIsNone(self.stream.read_archive("2099-01-01"))

    def test_list_archives(self) -> None:
        self.stream.archive_today("2025-01-01")
        self.stream.archive_today("2025-01-02")
        archives = self.stream.list_archives()
        self.assertIn("2025-01-01", archives)
        self.assertIn("2025-01-02", archives)

    def test_list_archives_empty(self) -> None:
        self.assertEqual(self.stream.list_archives(), [])


class SelfStreamDiaryTest(unittest.TestCase):
    """日记读写测试。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.stream = SelfStream(base_dir=Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_write_and_read_diary(self) -> None:
        self.stream.write_diary("2025-03-15", "# 今天\n\n不错。")
        self.assertIn("不错", self.stream.read_diary("2025-03-15") or "")

    def test_read_nonexistent_diary(self) -> None:
        self.assertIsNone(self.stream.read_diary("2099-01-01"))


class SelfStreamBuildContextTest(unittest.TestCase):
    """build_context 组装测试。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.stream = SelfStream(base_dir=Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_build_context_includes_state(self) -> None:
        self.stream.update_state("- 精力：高\n")
        ctx = self.stream.build_context(include_state=True)
        self.assertIn("精力：高", ctx)

    def test_build_context_excludes_state_when_false(self) -> None:
        self.stream.update_state("- 精力：高\n")
        ctx = self.stream.build_context(include_state=False)
        self.assertNotIn("自我状态", ctx)

    def test_build_context_includes_memory_list(self) -> None:
        self.stream.write_memory("alice", "...")
        self.stream.write_memory("bob", "...")
        ctx = self.stream.build_context()
        self.assertIn("alice", ctx)
        self.assertIn("bob", ctx)

    def test_build_context_includes_specific_memories(self) -> None:
        self.stream.write_memory("alice", "Alice 喜欢古典音乐。")
        ctx = self.stream.build_context(memory_names=["alice"])
        self.assertIn("古典音乐", ctx)

    def test_build_context_includes_recent(self) -> None:
        self.stream.append_experience("独一无二的体验内容。")
        ctx = self.stream.build_context(recent_chars=4000)
        self.assertIn("独一无二的体验内容", ctx)


if __name__ == "__main__":
    unittest.main()
