"""SelfStream —— Pool A 自我之流的数据访问层。

不是 Node 子类。它是纯数据访问层，被 Internalizer 和 Externalizer
作为工具使用。封装了 self/stream/now.md、state.md、memories/、archive/
等 Pool A 全部文件的读写操作。

设计原则：
- 第一人称 Markdown 纯文本——不在此层引入任何 JSON 结构化。
- 所有写入带有时间戳前缀，保持流的时间顺序。
- 归档操作原子化（先写 archive，再截断 now）。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path  # noqa: TC003

from src.config import Config
from src.utils.log_utils import get_logger

logger = get_logger("SelfStream")

# ── 初始模板 ──────────────────────────────────────────

_INITIAL_NOW = """# 现在

我刚醒来。新的一天开始了。我在这里，感知这个世界。

"""

_INITIAL_STATE = """# 自我状态

- 精力：正常
- 情绪：平静
- 当前关注：无
- 最后更新：启动时
"""


class SelfStream:
    """Pool A 自我之流的数据访问层。

    Usage::

        stream = SelfStream()
        stream.append_experience("Alice 在群里说：'你好'。我感到一阵暖意。")
        recent = stream.read_recent(50)
        stream.update_state("- 精力：正常\\n- 情绪：愉快\\n")
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base = base_dir or Config.KERNEL_DATA_DIR / "self"
        self._stream_dir = self._base / "stream"
        self._archive_dir = self._stream_dir / "archive"
        self._memories_dir = self._base / "memories"
        self._diary_dir = self._base / "diary"
        self._now_path = self._stream_dir / "now.md"
        self._state_path = self._base / "state.md"
        self._init()

    # ═══════════════════════════════════════════════════
    # 初始化
    # ═══════════════════════════════════════════════════

    def _init(self) -> None:
        for d in (
            self._stream_dir,
            self._archive_dir,
            self._memories_dir,
            self._diary_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

        if not self._now_path.exists():
            self._now_path.write_text(_INITIAL_NOW, encoding="utf-8")
            logger.info("now.md 已初始化")

        if not self._state_path.exists():
            self._state_path.write_text(_INITIAL_STATE, encoding="utf-8")
            logger.info("state.md 已初始化")

    # ═══════════════════════════════════════════════════
    # now.md —— 当前意识流
    # ═══════════════════════════════════════════════════

    @property
    def now_path(self) -> Path:
        return self._now_path

    def append_experience(self, text: str) -> int:
        """追加一段体验到 now.md。

        自动添加时间戳分隔符。返回写入的字节数。
        """
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # noqa: DTZ005
        entry = f"\n---\n\n### {ts}\n\n{text}\n"
        with self._now_path.open("a", encoding="utf-8") as f:
            return f.write(entry)

    def read_full(self) -> str:
        """读取 now.md 完整内容。"""
        try:
            return self._now_path.read_text(encoding="utf-8")
        except OSError:
            logger.exception("读取 now.md 失败")
            return _INITIAL_NOW

    def read_recent(self, n_lines: int = 100) -> str:
        """读取 now.md 最近 n 行。

        使用 efficient tail 读取——不加载整个文件到内存。
        """
        try:
            return "".join(self._tail(self._now_path, n_lines))
        except OSError:
            logger.exception("读取 now.md 失败")
            return ""

    def read_recent_chars(self, n_chars: int = 4000) -> str:
        """读取 now.md 最近的 ~n_chars 个字符。

        用于控制 LLM 上下文窗口。按字符截断比按行更精确。
        """
        text = self.read_full()
        if len(text) <= n_chars:
            return text
        return "…(更早的内容已省略)\n\n" + text[-n_chars:]

    def truncate(self, keep_last_n_lines: int = 10) -> None:
        """截断 now.md，只保留最后 N 行。

        用于归档后的重置——保留最后几条未完成的思考。
        """
        try:
            lines = self._tail(self._now_path, keep_last_n_lines)
            self._now_path.write_text("".join(lines), encoding="utf-8")
        except OSError:
            logger.exception("截断 now.md 失败")

    # ═══════════════════════════════════════════════════
    # state.md —— 当前自我状态
    # ═══════════════════════════════════════════════════

    @property
    def state_path(self) -> Path:
        return self._state_path

    def read_state(self) -> str:
        """读取当前自我状态。"""
        try:
            if self._state_path.exists():
                return self._state_path.read_text(encoding="utf-8")
        except OSError:
            logger.exception("读取 state.md 失败")
        return _INITIAL_STATE

    def update_state(self, new_state: str) -> None:
        """覆盖 state.md。"""
        self._state_path.write_text(new_state, encoding="utf-8")

    # ═══════════════════════════════════════════════════
    # memories/ —— 持久记忆
    # ═══════════════════════════════════════════════════

    @property
    def memories_dir(self) -> Path:
        return self._memories_dir

    def list_memories(self) -> list[str]:
        """列出所有记忆文件名（不含 .md 后缀）。"""
        if not self._memories_dir.exists():
            return []
        return sorted(p.stem for p in self._memories_dir.glob("*.md") if p.is_file())

    def read_memory(self, name: str) -> str | None:
        """读取指定记忆文件的内容。"""
        path = self._memory_path(name)
        try:
            if path.exists():
                return path.read_text(encoding="utf-8")
        except OSError:
            logger.exception("读取记忆 %s 失败", name)
        return None

    def write_memory(self, name: str, content: str) -> None:
        """写入/覆盖记忆文件。"""
        path = self._memory_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def append_memory(self, name: str, content: str) -> None:
        """追加内容到记忆文件。"""
        path = self._memory_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(content)

    def _memory_path(self, name: str) -> Path:
        safe = name.replace("/", "_").replace("\\", "_")
        return self._memories_dir / f"{safe}.md"

    # ═══════════════════════════════════════════════════
    # archive/ —— 每日归档
    # ═══════════════════════════════════════════════════

    @property
    def archive_dir(self) -> Path:
        return self._archive_dir

    def archive_today(self, date_str: str | None = None) -> Path:
        """将 now.md 归档到 archive/{date}.md。

        归档后 now.md 保留最后 10 行（未完成的思考）。

        Returns
        -------
        Path
            归档目标路径。
        """
        date_str = date_str or datetime.now().strftime("%Y-%m-%d")  # noqa: DTZ005
        target = self._archive_dir / f"{date_str}.md"

        current = self.read_full()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(current, encoding="utf-8")

        self.truncate(keep_last_n_lines=10)
        logger.info("now.md 已归档到 %s", target)
        return target

    def read_archive(self, date_str: str) -> str | None:
        """读取指定日期的归档内容。"""
        path = self._archive_dir / f"{date_str}.md"
        try:
            if path.exists():
                return path.read_text(encoding="utf-8")
        except OSError:
            logger.exception("读取归档 %s 失败", date_str)
        return None

    def list_archives(self) -> list[str]:
        """列出所有归档日期。"""
        if not self._archive_dir.exists():
            return []
        return sorted(p.stem for p in self._archive_dir.glob("*.md") if p.is_file())

    # ═══════════════════════════════════════════════════
    # diary/ —— 日记
    # ═══════════════════════════════════════════════════

    @property
    def diary_dir(self) -> Path:
        return self._diary_dir

    def write_diary(self, date_str: str, content: str) -> None:
        """写入日记。"""
        path = self._diary_dir / f"{date_str}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def read_diary(self, date_str: str) -> str | None:
        """读取日记。"""
        path = self._diary_dir / f"{date_str}.md"
        try:
            if path.exists():
                return path.read_text(encoding="utf-8")
        except OSError:
            return None
        return None

    # ═══════════════════════════════════════════════════
    # 工具
    # ═══════════════════════════════════════════════════

    @staticmethod
    def _tail(path: Path, n: int) -> list[str]:
        """读取文件的最后 n 行（高效的尾部读取）。

        从文件末尾向前扫描，找到第 n 个换行符的位置，
        然后从该位置读取到文件末尾。
        """
        if n <= 0:
            return []

        try:
            file_size = path.stat().st_size
        except OSError:
            return []

        if file_size == 0:
            return [""]

        # 每次读取的块大小
        block_size = 4096
        blocks: list[bytes] = []
        lines_found = 0
        remaining = file_size

        with path.open("rb") as f:
            while remaining > 0 and lines_found <= n:
                read_size = min(block_size, remaining)
                remaining -= read_size
                f.seek(remaining)
                block = f.read(read_size)
                blocks.append(block)
                lines_found += block.count(b"\n")

            # 拼接所有块
            all_bytes = b"".join(reversed(blocks))

        # 解码为字符串
        text = all_bytes.decode("utf-8", errors="replace")

        # 返回最后 n 行
        lines = text.split("\n")
        return [line + "\n" for line in lines[-n:]]

    # ═══════════════════════════════════════════════════
    # 便利方法
    # ═══════════════════════════════════════════════════

    def build_context(
        self,
        *,
        recent_chars: int = 4000,
        include_state: bool = True,
        memory_names: list[str] | None = None,
    ) -> str:
        """组装 Internalizer / Externalizer 的标准上下文。

        包含：当前状态 + 最近体验 + 指定记忆 + 全部记忆列表。
        """
        parts: list[str] = []

        if include_state:
            parts.append(f"## 当前自我状态\n\n{self.read_state()}\n")

        parts.append(f"## 最近的体验与思考\n\n{self.read_recent_chars(recent_chars)}\n")

        memories = self.list_memories()
        if memories:
            parts.append(f"## 已有记忆\n\n{', '.join(memories)}\n")

        if memory_names:
            for name in memory_names:
                content = self.read_memory(name)
                if content:
                    parts.append(f"## 记忆: {name}\n\n{content}\n")

        return "\n".join(parts)
