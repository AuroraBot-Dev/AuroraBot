"""kernel-α: XiaoGuang-Bot PolarisBot → AuroraBot PolarisAgent 单体节点

移植自 XiaoGuang-Bot/polaris/main.py + polaris/tasks/diary.py，
保留原耦合度：history.json 对话历史、脉冲门控、日记/印象记忆系统。
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, TYPE_CHECKING

from src.brain.ai.llm_gate import llm_chat
from src.brain.kernel.base import Agent, FileUpdate
from src.brain.kernel.state_store import kernel_data_dir, move_to_done
from src.config import Config
from src.utils.log_utils import get_logger
from src.utils.time_utils import now_text

import src.brain.prompts as prompts

if TYPE_CHECKING:
    from src.platform.application_host import ApplicationHost

logger = get_logger("PolarisAgent")

# ═══════════════════════════════════════════════════════════════
# 常量（移植自 XiaoGuang-Bot polaris/config.py）
# ═══════════════════════════════════════════════════════════════

REPLY_DEBOUNCE_SECONDS = 2.0
RECENT_MESSAGE_LIMIT = 6  # 分钟
MESSAGE_WINDOW = 300
DIARY_RUN_HOUR = 23
DIARY_RUN_MINUTE = 20

# 脉冲门控系统提示词
IMPULSE_GATE_PROMPT = prompts.IMPULSE_GATE.get_content()

# 静默回复文本（命中后不发送）
SILENT_REPLY_TEXTS = {"（与我无关，不回）"}

# ── 日记系统常量 ──────────────────────────────────
_EVENT_LINE_PATTERN = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) 的时候, "
    r"(?P<user_id>\d+) 在(?:(?:群聊 (?P<group_id>\d+))|(?:与你的私聊))中说: "
    r"(?P<content>.*)$"
)
_MOOD_POSITIVE_WORDS = {"开心", "哈哈", "晚安", "喜欢", "谢谢", "好耶", "可爱", "奶茶"}
_MOOD_NEGATIVE_WORDS = {"难过", "烦", "累", "生气", "困", "崩溃", "伤心", "压力"}
_MEMORY_HINT_WORDS = {
    "叫我",
    "我是",
    "外号",
    "昵称",
    "喜欢",
    "讨厌",
    "工作",
    "学习",
    "生日",
    "明天",
    "晚安",
}


# ═══════════════════════════════════════════════════════════════
# 日记系统（移植自 XiaoGuang-Bot polaris/tasks/diary.py）
# ═══════════════════════════════════════════════════════════════


def _today_date_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _load_history(history_path: Path) -> list[dict[str, Any]]:
    return _load_json(history_path, [])


def _load_soul_text(history: list[dict[str, Any]], soul_path: Path) -> str:
    if soul_path.exists():
        return soul_path.read_text(encoding="utf-8")
    if history and history[0].get("role") == "system":
        return str(history[0].get("content", ""))
    return ""


def _parse_user_events(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for message in history:
        if message.get("role") != "user":
            continue
        fallback_user_id = str(message.get("name", "unknown"))
        content = str(message.get("content", ""))
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            matched = _EVENT_LINE_PATTERN.match(line)
            if matched:
                timestamp_text = matched.group("timestamp")
                try:
                    ts = datetime.strptime(timestamp_text, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    ts = None
                group_id = matched.group("group_id")
                events.append(
                    {
                        "user_id": matched.group("user_id"),
                        "timestamp": timestamp_text,
                        "date": ts.date().isoformat() if ts else None,
                        "scene": "group" if group_id else "private",
                        "group_id": group_id,
                        "content": matched.group("content").strip(),
                        "raw_line": line,
                    }
                )
            else:
                events.append(
                    {
                        "user_id": fallback_user_id,
                        "timestamp": None,
                        "date": None,
                        "scene": "unknown",
                        "group_id": None,
                        "content": line,
                        "raw_line": line,
                    }
                )
    return events


def _safe_parse_json_object(content: str) -> dict[str, Any]:
    left = content.find("{")
    right = content.rfind("}")
    if left == -1 or right == -1 or right <= left:
        raise ValueError("LLM did not return a JSON object")
    return json.loads(content[left : right + 1])


async def _extract_with_llm(system_prompt: str, user_prompt: str) -> dict[str, Any]:
    response = await llm_chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=1024,
        temperature=0.2,
    )
    content = (response or "").strip()
    return _safe_parse_json_object(content)


async def _extract_daily_diary_async(
    soul_text: str,
    day: str,
    day_events: list[dict[str, Any]],
) -> dict[str, Any]:
    event_lines = [event["raw_line"] for event in day_events[-200:]]
    if not event_lines:
        return {
            "title": f"小光日记 {day}",
            "summary": "今天比较安静，聊天记录不多。",
            "major_events": [],
            "important_events": [],
            "mood": "平静",
            "mood_reason": "没有明显波动事件。",
            "reflection": "慢慢来，保持观察和记录。",
        }

    system_prompt = (
        "你是小光的日记整理器。你会根据人格设定和当天聊天，"
        "写出像人类一样的日记结构。只输出 JSON，格式如下："
        '{"title":"","summary":"","major_events":[""],'
        '"important_events":[""],"mood":"","mood_reason":"","reflection":""}'
    )
    user_prompt = (
        f"日期：{day}\n"
        f"人格文档：\n{soul_text}\n\n"
        "今日聊天记录：\n"
        + "\n".join(event_lines)
        + "\n\n要求：major_events 2~5 条，important_events 1~3 条，语气真实自然。"
    )

    try:
        payload = await _extract_with_llm(system_prompt, user_prompt)
        return {
            "title": str(payload.get("title") or f"小光日记 {day}").strip(),
            "summary": str(payload.get("summary") or "").strip(),
            "major_events": [
                str(item).strip()
                for item in (payload.get("major_events") or [])
                if str(item).strip()
            ][:5],
            "important_events": [
                str(item).strip()
                for item in (payload.get("important_events") or [])
                if str(item).strip()
            ][:3],
            "mood": str(payload.get("mood") or "平静").strip(),
            "mood_reason": str(payload.get("mood_reason") or "").strip(),
            "reflection": str(payload.get("reflection") or "").strip(),
        }
    except Exception as exc:
        logger.warning("daily diary extract failed: %s", exc)

    mood_score = 0
    for event in day_events:
        text = event["content"]
        if any(word in text for word in _MOOD_POSITIVE_WORDS):
            mood_score += 1
        if any(word in text for word in _MOOD_NEGATIVE_WORDS):
            mood_score -= 1

    mood = "轻松" if mood_score > 0 else "低落" if mood_score < 0 else "平静"
    major_events = [event["raw_line"] for event in day_events[-5:]]
    important_events = [
        event["raw_line"]
        for event in day_events
        if any(word in event["content"] for word in _MEMORY_HINT_WORDS)
    ][:3]
    return {
        "title": f"小光日记 {day}",
        "summary": "今天和大家有一些交流，整体节奏还算自然。",
        "major_events": major_events,
        "important_events": important_events,
        "mood": mood,
        "mood_reason": "基于当天聊天语气关键词的粗略判断。",
        "reflection": "继续在真实互动中积累记忆。",
    }


async def _extract_user_daily_update(
    *,
    user_id: str,
    soul_text: str,
    day: str,
    user_day_events: list[dict[str, Any]],
    relation_candidates: list[str],
) -> dict[str, Any]:
    if not user_day_events:
        return {
            "important_info_append": {
                "names": [],
                "basic_info": [],
                "nicknames": [],
                "personality_traits": [],
            },
            "relationships_daily": [],
            "subjective_impression_daily": "",
            "important_memories_daily": [],
        }

    records = [event["raw_line"] for event in user_day_events[-80:]]
    system_prompt = (
        "你是关系记忆提取器。根据人格与当日对话，为指定用户提取记忆。"
        "只输出 JSON，格式如下："
        '{"important_info_append":{"names":[""],"basic_info":[""],'
        '"nicknames":[""],"personality_traits":[""]},'
        '"relationships_daily":[{"target_user_id":"","relation":"","evidence":""}],'
        '"subjective_impression_daily":"","important_memories_daily":[""]}'
    )
    user_prompt = (
        f"日期：{day}\n"
        f"目标用户：{user_id}\n"
        f"人格文档：\n{soul_text}\n\n"
        f"可能相关的人：{', '.join(relation_candidates) if relation_candidates else '无'}\n"
        "该用户今日聊天：\n"
        + "\n".join(records)
        + "\n\n要求：关系只填今天可推断出的内容。"
    )

    try:
        payload = await _extract_with_llm(system_prompt, user_prompt)
        info = payload.get("important_info_append") or {}
        relation_rows = payload.get("relationships_daily") or []
        return {
            "important_info_append": {
                "names": [
                    str(item).strip()
                    for item in (info.get("names") or [])
                    if str(item).strip()
                ],
                "basic_info": [
                    str(item).strip()
                    for item in (info.get("basic_info") or [])
                    if str(item).strip()
                ],
                "nicknames": [
                    str(item).strip()
                    for item in (info.get("nicknames") or [])
                    if str(item).strip()
                ],
                "personality_traits": [
                    str(item).strip()
                    for item in (info.get("personality_traits") or [])
                    if str(item).strip()
                ],
            },
            "relationships_daily": [
                {
                    "target_user_id": str(row.get("target_user_id") or "").strip(),
                    "relation": str(row.get("relation") or "").strip(),
                    "evidence": str(row.get("evidence") or "").strip(),
                }
                for row in relation_rows
                if isinstance(row, dict)
                and str(row.get("target_user_id") or "").strip()
                and str(row.get("relation") or "").strip()
            ],
            "subjective_impression_daily": str(
                payload.get("subjective_impression_daily") or ""
            ).strip(),
            "important_memories_daily": [
                str(item).strip()
                for item in (payload.get("important_memories_daily") or [])
                if str(item).strip()
            ][:6],
        }
    except Exception as exc:
        logger.warning("user daily extract failed for user=%s: %s", user_id, exc)

    fallback_memories = [
        event["raw_line"]
        for event in user_day_events
        if any(word in event["content"] for word in _MEMORY_HINT_WORDS)
    ][:4]
    return {
        "important_info_append": {
            "names": [],
            "basic_info": [],
            "nicknames": [],
            "personality_traits": [],
        },
        "relationships_daily": [],
        "subjective_impression_daily": "今天互动自然，先继续观察。",
        "important_memories_daily": fallback_memories,
    }


def _uniq_append(old_items: list[str], new_items: list[str]) -> list[str]:
    merged: list[str] = []
    for item in old_items + new_items:
        item_clean = str(item).strip()
        if item_clean and item_clean not in merged:
            merged.append(item_clean)
    return merged


def _merge_relationships(
    existing: list[dict[str, Any]],
    today_rows: list[dict[str, Any]],
    day: str,
) -> list[dict[str, Any]]:
    merged = [row for row in existing if isinstance(row, dict)]
    index_by_target: dict[str, int] = {
        str(row.get("target_user_id")): idx
        for idx, row in enumerate(merged)
        if str(row.get("target_user_id", "")).strip()
    }
    for row in today_rows:
        target = str(row.get("target_user_id", "")).strip()
        if not target:
            continue
        new_row = {
            "target_user_id": target,
            "relation": str(row.get("relation", "")).strip(),
            "evidence": str(row.get("evidence", "")).strip(),
            "updated_on": day,
        }
        if target in index_by_target:
            merged[index_by_target[target]] = new_row
        else:
            merged.append(new_row)
            index_by_target[target] = len(merged) - 1
    return merged


async def extract_daily_memory_bundle(
    history_path: Path,
    soul_path: Path,
    target_day: str | None = None,
) -> dict[str, Any]:
    day = target_day or _today_date_str()
    history = _load_history(history_path)
    soul_text = _load_soul_text(history, soul_path)
    events = _parse_user_events(history)

    if target_day:
        day_events = [event for event in events if event.get("date") == day]
    else:
        day_events = list(events)

    known_user_ids = sorted(
        {event["user_id"] for event in day_events if event.get("user_id")}
    )

    day_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    group_user_map: dict[str, set[str]] = defaultdict(set)
    for event in day_events:
        user_id = event["user_id"]
        day_by_user[user_id].append(event)
        group_id = event.get("group_id")
        if group_id:
            group_user_map[group_id].add(user_id)

    relation_candidates: dict[str, list[str]] = defaultdict(list)
    for users in group_user_map.values():
        for user_id in users:
            relation_candidates[user_id].extend(
                sorted(uid for uid in users if uid != user_id)
            )
    for user_id in relation_candidates:
        relation_candidates[user_id] = sorted(set(relation_candidates[user_id]))

    diary_payload = await _extract_daily_diary_async(
        soul_text=soul_text,
        day=day,
        day_events=day_events,
    )

    user_daily_updates: dict[str, dict[str, Any]] = {}
    for user_id in known_user_ids:
        user_daily_updates[user_id] = await _extract_user_daily_update(
            user_id=user_id,
            soul_text=soul_text,
            day=day,
            user_day_events=day_by_user.get(user_id, []),
            relation_candidates=relation_candidates.get(user_id, []),
        )

    return {
        "date": day,
        "events_count": len(day_events),
        "known_user_ids": known_user_ids,
        "day_events": day_events,
        "diary_payload": diary_payload,
        "user_daily_updates": user_daily_updates,
    }


def apply_daily_memory_bundle(
    bundle: dict[str, Any],
    *,
    diary_dir: Path,
    impression_dir: Path,
) -> dict[str, Any]:
    day = str(bundle.get("date") or _today_date_str())
    known_user_ids = [str(item) for item in (bundle.get("known_user_ids") or [])]
    updates = bundle.get("user_daily_updates") or {}
    diary_payload = bundle.get("diary_payload") or {}

    impression_count = 0
    impression_dir.mkdir(parents=True, exist_ok=True)

    for user_id in known_user_ids:
        update = updates.get(user_id) or {}
        path = impression_dir / f"{user_id}.json"
        current = _load_json(path, {})
        important = current.get("important_info") or {}

        new_important = {
            "names": _uniq_append(
                important.get("names", []),
                (update.get("important_info_append") or {}).get("names", []),
            ),
            "basic_info": _uniq_append(
                important.get("basic_info", []),
                (update.get("important_info_append") or {}).get("basic_info", []),
            ),
            "nicknames": _uniq_append(
                important.get("nicknames", []),
                (update.get("important_info_append") or {}).get("nicknames", []),
            ),
            "personality_traits": _uniq_append(
                important.get("personality_traits", []),
                (update.get("important_info_append") or {}).get(
                    "personality_traits", []
                ),
            ),
        }

        old_relations = current.get("relationships", [])
        today_relations = update.get("relationships_daily", [])
        merged_relations = _merge_relationships(old_relations, today_relations, day)

        daily_relation_updates = current.get("daily_relationship_updates", [])
        if today_relations:
            daily_relation_updates = list(daily_relation_updates) + [
                {"date": day, "updates": today_relations}
            ]

        old_memories = current.get("important_memories", [])
        new_memories = _uniq_append(
            list(old_memories), list(update.get("important_memories_daily", []))
        )

        subjective_impression = str(
            update.get("subjective_impression_daily")
            or current.get("subjective_impression", "")
        ).strip()

        payload = {
            "user_id": user_id,
            "created_at": current.get("created_at")
            or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "important_info": new_important,
            "relationships": merged_relations,
            "daily_relationship_updates": daily_relation_updates,
            "subjective_impression": subjective_impression,
            "important_memories": new_memories,
            "last_active_date": (
                day
                if update.get("important_memories_daily")
                else current.get("last_active_date")
            ),
        }
        _write_json(path, payload)
        impression_count += 1

    diary_markdown = _render_diary_markdown(day, diary_payload)
    diary_json_payload = {
        "date": day,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "events_count": bundle.get("events_count", 0),
        "diary": diary_payload,
    }

    diary_dir.mkdir(parents=True, exist_ok=True)
    diary_md_path = diary_dir / f"{day}.md"
    diary_json_path = diary_dir / f"{day}.json"
    diary_md_path.write_text(diary_markdown, encoding="utf-8")
    _write_json(diary_json_path, diary_json_payload)

    return {
        "date": day,
        "impression_count": impression_count,
        "diary_path": str(diary_md_path),
        "diary_json_path": str(diary_json_path),
    }


def _render_diary_markdown(day: str, diary_payload: dict[str, Any]) -> str:
    title = str(diary_payload.get("title") or f"小光日记 {day}").strip()
    summary = str(diary_payload.get("summary") or "").strip()
    mood = str(diary_payload.get("mood") or "平静").strip()
    mood_reason = str(diary_payload.get("mood_reason") or "").strip()
    reflection = str(diary_payload.get("reflection") or "").strip()
    major_events = [
        str(item).strip()
        for item in (diary_payload.get("major_events") or [])
        if str(item).strip()
    ]
    important_events = [
        str(item).strip()
        for item in (diary_payload.get("important_events") or [])
        if str(item).strip()
    ]

    lines = [f"# {title}", "", f"- 日期：{day}", f"- 心情：{mood}"]
    if mood_reason:
        lines.append(f"- 心情原因：{mood_reason}")
    lines.append("")

    if summary:
        lines.extend(["## 今日概述", "", summary, ""])

    lines.extend(["## 主要事件", ""])
    if major_events:
        for item in major_events:
            lines.append(f"- {item}")
    else:
        lines.append("- 今天相对平稳。")
    lines.append("")

    lines.extend(["## 重要事件", ""])
    if important_events:
        for item in important_events:
            lines.append(f"- {item}")
    else:
        lines.append("- 暂无特别重大的事件。")
    lines.append("")

    lines.extend(["## 自我反思", "", reflection or "继续沉淀记忆，保持真实交流。", ""])
    return "\n".join(lines)


def _archive_history_snapshot(
    history_path: Path, archive_dir: Path, day: str
) -> str | None:
    history = _load_history(history_path)
    has_chat = any(m.get("role") != "system" for m in history)
    if not has_chat:
        return None

    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{day}.json"
    if archive_path.exists():
        suffix = datetime.now().strftime("%H%M%S")
        archive_path = archive_dir / f"{day}_{suffix}.json"
    _write_json(archive_path, history)
    return str(archive_path)


def _reset_history_to_system_only(history_path: Path, soul_path: Path) -> None:
    history = _load_history(history_path)
    soul_text = _load_soul_text(history, soul_path).strip()
    if not soul_text:
        soul_text = "# 灵魂文档\n"
    _write_json(history_path, [{"role": "system", "content": soul_text}])


async def run_diary_job(
    *,
    history_path: Path,
    soul_path: Path,
    diary_dir: Path,
    impression_dir: Path,
    archive_dir: Path,
    target_day: str | None = None,
) -> dict[str, Any]:
    """执行完整日记作业：提取 → 写入 → 归档 → 重置历史。"""
    bundle = await extract_daily_memory_bundle(
        history_path=history_path,
        soul_path=soul_path,
        target_day=target_day,
    )
    result = apply_daily_memory_bundle(
        bundle,
        diary_dir=diary_dir,
        impression_dir=impression_dir,
    )
    archive_path = _archive_history_snapshot(history_path, archive_dir, result["date"])
    _reset_history_to_system_only(history_path, soul_path)
    result["history_archive_path"] = archive_path
    result["history_reset"] = True
    return result


# ═══════════════════════════════════════════════════════════════
# PolarisAgent
# ═══════════════════════════════════════════════════════════════


class PolarisAgent(Agent):
    """kernel-α: XiaoGuang-Bot PolarisBot 单体移植节点。

    守护 ``inbox/pending/event_message.received_*.json``，
    处理 QQ 消息事件：防抖合并 → 脉冲门控 → LLM 回复 → 发送。

    内部维护：
    - history.json 对话历史（asyncio.Lock 保护）
    - 最近消息滑动窗口（按群/私聊分组）
    - 会话版本号（防抖用）
    - 日记定时调度器（后台 asyncio.Task）
    """

    _default_guards = ["inbox/pending/event_message_received_*.json"]

    def __init__(
        self,
        node_id: str,
        host: ApplicationHost | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(node_id, host=host, **kwargs)

        # ── 数据路径（保留 XiaoGuang-Bot 原始目录结构） ──
        self._history_path = Config.DATA_DIR / "history.json"
        self._soul_path = Config.PROMPTS_DIR / "SOUL.md"
        self._diary_dir = Config.DATA_DIR / "diary"
        self._impression_dir = Config.DATA_DIR / "impressions"
        self._archive_dir = Config.DATA_DIR / "history_archive"

        # ── 运行时状态 ──
        self._history_lock = asyncio.Lock()
        self._session_versions: dict[str, int] = {}
        self._pending_inputs: dict[str, list[dict[str, Any]]] = {}
        self._group_recent: dict[int, deque[tuple[float, str]]] = defaultdict(
            lambda: deque()
        )
        self._private_recent: dict[str, deque[tuple[float, str]]] = defaultdict(
            lambda: deque()
        )

        # ── 日记调度器 ──
        self._diary_task: asyncio.Task[None] | None = None

        # ── SOUL ──
        self._soul = ""
        self._init_data()

    # ── 生命周期 ──────────────────────────────────────

    def _init_data(self) -> None:
        """初始化 SOUL 与 history.json。"""
        # 加载 SOUL
        self._soul = prompts.SOUL.get_content()

        # 确保目录存在
        for d in (self._diary_dir, self._impression_dir, self._archive_dir):
            d.mkdir(parents=True, exist_ok=True)

        # 初始化 history.json（空则写入 system 消息）
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        is_empty = False
        if self._history_path.exists():
            content = self._history_path.read_text(encoding="utf-8").strip()
            if not content:
                is_empty = True
            else:
                try:
                    history = json.loads(content)
                    is_empty = history == []
                except json.JSONDecodeError:
                    logger.error("history.json 格式错误，将重新初始化")
                    is_empty = True
        else:
            is_empty = True

        if is_empty:
            history = [{"role": "system", "content": self._soul}]
            self._history_path.write_text(
                json.dumps(history, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    async def run(self) -> None:
        """启动节点主循环 + 日记后台调度器。"""
        self._diary_task = asyncio.create_task(self._diary_scheduler_loop())
        logger.info(
            "PolarisAgent: 日记调度器已启动, 每日 %02d:%02d 执行",
            DIARY_RUN_HOUR,
            DIARY_RUN_MINUTE,
        )
        try:
            await super().run()
        finally:
            if self._diary_task is not None:
                self._diary_task.cancel()
                self._diary_task = None

    # ── execute ───────────────────────────────────────

    async def execute(self) -> list[FileUpdate]:
        """扫描待处理消息事件，启动防抖→门控→回复流水线。

        处理完成的输入文件移入 done/ 子目录。
        本方法快速返回（仅 spawn 后台任务），不阻塞事件循环。
        """
        pending_dir = kernel_data_dir / "inbox" / "pending"
        if not pending_dir.exists():
            return []

        event_files = sorted(pending_dir.glob("event_message_received_*.json"))
        if not event_files:
            return []

        done_dir = pending_dir / "done"
        done_dir.mkdir(parents=True, exist_ok=True)

        for event_file in event_files:
            try:
                data = json.loads(event_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("PolarisAgent 读取事件失败 %s: %s", event_file.name, exc)
                move_to_done(event_file, done_dir)
                continue

            if not isinstance(data, dict):
                move_to_done(event_file, done_dir)
                continue

            payload = data.get("payload", {})
            if not isinstance(payload, dict):
                logger.warning("PolarisAgent: 事件 payload 无效 %s", event_file.name)
                move_to_done(event_file, done_dir)
                continue

            text = str(payload.get("text", "")).strip()
            if not text:
                logger.debug("PolarisAgent: 事件文本为空 %s", event_file.name)
                move_to_done(event_file, done_dir)
                continue

            # ── 校验通过，消费源文件 ──
            move_to_done(event_file, done_dir)

            user_id = str(payload.get("user_id", ""))
            session_id = str(payload.get("session_id", ""))
            is_group = bool(payload.get("is_group", False))
            group_id = str(payload.get("group_id", "")) if is_group else None

            session_key = (
                f"group:{group_id}:{user_id}" if is_group else f"private:{user_id}"
            )

            logger.info(
                "PolarisAgent: 收到消息 session=%s user=%s is_group=%s text=%.60s",
                session_key,
                user_id,
                is_group,
                text,
            )

            # 构建格式化的历史行（与 XiaoGuang-Bot 完全一致）
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            if is_group and group_id:
                input_line = (
                    f"{timestamp} 的时候, {user_id} 在群聊 {group_id} 中说: {text}"
                )
                scene_name = "群聊"
            else:
                input_line = f"{timestamp} 的时候, {user_id} 在与你的私聊中说: {text}"
                scene_name = "私聊"

            # 更新最近消息滑动窗口
            if is_group:
                self._append_recent_message(
                    self._group_recent[int(group_id or 0)], input_line
                )
            else:
                self._append_recent_message(self._private_recent[user_id], input_line)

            # 加入待处理队列并更新版本号
            entry = {
                "user_id": user_id,
                "session_key": session_key,
                "session_id": session_id,
                "input_line": input_line,
                "text": text,
                "is_group": is_group,
                "group_id": group_id,
                "scene_name": scene_name,
            }
            self._pending_inputs.setdefault(session_key, []).append(entry)
            current_version = self._session_versions.get(session_key, 0) + 1
            self._session_versions[session_key] = current_version

            # 启动防抖任务
            asyncio.create_task(self._debounce_and_reply(session_key, current_version))

        return []

    # ── 防抖与回复 ────────────────────────────────────

    async def _debounce_and_reply(self, session_key: str, version: int) -> None:
        """等待防抖窗口后，若版本未变则合并输入并处理。"""
        await asyncio.sleep(REPLY_DEBOUNCE_SECONDS)

        if self._session_versions.get(session_key) != version:
            logger.debug("PolarisAgent: 防抖被新消息打断 (session=%s)", session_key)
            return  # 新消息已到达，由它接管

        entries = self._pending_inputs.pop(session_key, [])
        if not entries:
            return

        # 合并为单条用户输入
        merged_input = "\n".join(entry["input_line"] for entry in entries)
        user_id = entries[0]["user_id"]
        session_id = entries[0]["session_id"]
        is_group = entries[0]["is_group"]
        group_id = entries[0]["group_id"]
        scene_name = entries[0]["scene_name"]

        logger.info(
            "PolarisAgent: 防抖完成 session=%s 合并 %d 条 → 脉冲门控",
            session_key,
            len(entries),
        )

        # ── 脉冲门控 ──
        recent_messages = (
            self._group_recent[int(group_id or 0)]
            if is_group
            else self._private_recent[user_id]
        )
        recent_lines = self._get_recent_lines(recent_messages)

        try:
            should_reply = await self._impulse_gate(
                scene_name, recent_lines, merged_input
            )
        except Exception:
            logger.exception("PolarisAgent 脉冲门控异常，默认跳过回复")
            return

        if not should_reply:
            logger.info("PolarisAgent: 脉冲门控判定不回复 (session=%s)", session_key)
            return

        logger.info("PolarisAgent: 脉冲门控通过 → LLM 回复生成")

        # ── LLM 回复生成 ──
        try:
            response = await self._generate_reply(user_id, merged_input)
        except Exception:
            logger.exception("PolarisAgent LLM 回复生成失败")
            return

        logger.info(
            "PolarisAgent: LLM 回复生成完成 len=%d preview=%.80s",
            len(response),
            response,
        )

        if self._session_versions.get(session_key) != version:
            logger.debug("PolarisAgent: 发送前版本已变更，丢弃回复")
            return  # 发送前再次检查版本

        # ── 分条发送 ──
        msgs = [
            segment.strip()
            for segment in re.split(r"[|｜]", response)
            if segment.strip()
        ]
        if not msgs:
            msgs = [response.strip()]

        fully_sent = True
        for msg in msgs:
            if self._session_versions.get(session_key) != version:
                fully_sent = False
                break
            if not msg.strip() or msg.strip() in SILENT_REPLY_TEXTS:
                continue

            # 模拟打字延迟
            delay = min(1.8, max(0.25, len(msg) * 0.06))
            await asyncio.sleep(delay)

            if self._session_versions.get(session_key) != version:
                fully_sent = False
                break

            try:
                if self._host is not None:
                    await self._host.invoke_command(
                        "im.polaris.qq.send_qq_message",
                        session_id=session_id,
                        text=msg,
                    )
                    logger.info(
                        "PolarisAgent: 已发送片段 len=%d session=%s",
                        len(msg),
                        session_id,
                    )
                else:
                    logger.warning("PolarisAgent: host 未注入, 无法发送消息")
            except Exception:
                logger.exception("PolarisAgent 发送消息失败")

        # 完整发送后写入 assistant 历史
        if fully_sent:
            await self._append_assistant_message(response)
            logger.info(
                "PolarisAgent: 回复已完成 session=%s user=%s total_len=%d",
                session_key,
                user_id,
                len(response),
            )

    # ── 脉冲门控 ──────────────────────────────────────

    async def _impulse_gate(
        self,
        scene_name: str,
        recent_lines: list[str],
        merged_input: str,
    ) -> bool:
        """调用 LLM 判断当前是否应该回复。"""
        recent_text = "\n".join(recent_lines) if recent_lines else "(暂无历史)"

        messages = [
            {"role": "system", "content": IMPULSE_GATE_PROMPT},
            {
                "role": "user",
                "content": (
                    f"人格文档：\n{self._soul}\n\n"
                    f"{scene_name}最近{RECENT_MESSAGE_LIMIT}分钟消息：\n{recent_text}\n\n"
                    f"当前用户连续输入合并后内容：\n{merged_input}\n\n"
                    "此刻是否要完整回复？请仅输出：是 或 否。"
                ),
            },
        ]

        try:
            response = await llm_chat(messages, max_tokens=64, temperature=0.0)
        except Exception:
            logger.exception("PolarisAgent 脉冲门控 LLM 调用失败，默认不回复")
            return False

        # 空响应兜底：模型返回空时放行回复（避免门控故障导致永远静默）
        if not response or not response.strip():
            logger.warning("PolarisAgent: 脉冲门控 LLM 返回空响应，默认放行回复")
            return True

        return self._parse_yes_no(response)

    @staticmethod
    def _parse_yes_no(text: str) -> bool:
        content = (text or "").strip()
        if content == "是":
            return True
        if content == "否":
            return False
        if '"reply":"是"' in content or '"reply": "是"' in content:
            return True
        if "是" in content:
            return True
        return False

    # ── LLM 回复生成 ──────────────────────────────────

    async def _generate_reply(self, user_id: str, merged_input: str) -> str:
        """构建记忆上下文 + 对话历史，调用 LLM 生成回复。"""
        # 先写用户消息到历史
        messages = await self._append_user_message(user_id, merged_input)

        # 构建记忆上下文（日记 + 印象）
        memory_context = self._build_memory_context(user_id)

        # 注入记忆上下文到消息列表
        if messages:
            messages = (
                messages[:1]
                + [{"role": "system", "content": memory_context}]
                + messages[1:]
            )
        else:
            messages = [{"role": "system", "content": memory_context}]

        response = await llm_chat(messages, max_tokens=512)
        return (response or "").strip()

    # ── 对话历史管理 ──────────────────────────────────

    async def _append_user_message(
        self,
        user_id: str,
        input_line: str,
    ) -> list[dict[str, Any]]:
        """将用户消息写入 history.json，返回裁剪后的消息列表（system + 最近 N 条）。"""
        async with self._history_lock:
            history = self._read_history()

            # 兜底合并：上一条同用户消息则拼接
            if (
                history
                and history[-1].get("role") == "user"
                and history[-1].get("name") == str(user_id)
            ):
                prev = history[-1].get("content", "")
                history[-1]["content"] = f"{prev}\n{input_line}" if prev else input_line
            else:
                history.append(
                    {
                        "role": "user",
                        "name": str(user_id),
                        "content": input_line,
                    }
                )

            self._write_history(history)

            # 裁剪：system + 最近 MESSAGE_WINDOW 条
            recent_start = max(1, len(history) - MESSAGE_WINDOW)
            return history[:1] + history[recent_start:]

    async def _append_assistant_message(self, content: str) -> None:
        """写入 assistant 消息到 history.json。"""
        async with self._history_lock:
            history = self._read_history()
            history.append({"role": "assistant", "content": content})
            self._write_history(history)

    def _read_history(self) -> list[dict[str, Any]]:
        """读取 history.json（调用方需持有 _history_lock）。"""
        try:
            if self._history_path.exists():
                content = self._history_path.read_text(encoding="utf-8").strip()
                if content:
                    data = json.loads(content)
                    if isinstance(data, list):
                        return data
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("PolarisAgent 读取 history.json 失败: %s", exc)
        return [{"role": "system", "content": self._soul}]

    def _write_history(self, history: list[dict[str, Any]]) -> None:
        """写入 history.json（调用方需持有 _history_lock）。"""
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        self._history_path.write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── 记忆上下文 ─────────────────────────────────────

    def _build_memory_context(self, current_user_id: str) -> str:
        """构建注入 LLM 的长期记忆上下文（前两天日记 + 人际关系印象）。"""
        diaries = self._load_previous_two_diaries()
        impressions = self._load_all_impressions()
        prioritized = self._prioritize_impressions(current_user_id, impressions)

        diary_lines = []
        for item in diaries:
            diary_lines.append(f"## {item['date']}")
            diary_lines.append(item["content"])
        diary_block = "\n".join(diary_lines) if diary_lines else "无"

        if prioritized:
            impression_block = json.dumps(prioritized, ensure_ascii=False, indent=2)
        else:
            impression_block = "{}"

        return (
            "以下是长期记忆上下文，请在回复时参考：\n\n"
            "【前两天日记】\n"
            f"{diary_block}\n\n"
            "【所有人际关系印象 JSON】\n"
            f"{impression_block}"
        )

    def _load_previous_two_diaries(self) -> list[dict[str, str]]:
        diaries: list[dict[str, str]] = []
        for days_ago in (1, 2):
            target_date = (datetime.now() - timedelta(days=days_ago)).strftime(
                "%Y-%m-%d"
            )
            json_path = self._diary_dir / f"{target_date}.json"
            md_path = self._diary_dir / f"{target_date}.md"

            if json_path.exists():
                try:
                    content = json_path.read_text(encoding="utf-8")
                    diaries.append({"date": target_date, "content": content})
                    continue
                except OSError:
                    pass
            if md_path.exists():
                try:
                    content = md_path.read_text(encoding="utf-8")
                    diaries.append({"date": target_date, "content": content})
                except OSError:
                    pass
        return diaries

    def _load_all_impressions(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if not self._impression_dir.exists():
            return payload
        for path in sorted(self._impression_dir.glob("*.json")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload[path.stem] = json.load(f)
            except Exception:
                continue
        return payload

    @staticmethod
    def _prioritize_impressions(
        current_user_id: str,
        impressions: dict[str, Any],
    ) -> dict[str, Any]:
        if not impressions:
            return {}

        user_key = str(current_user_id)
        direct_related_ids: set[str] = set()

        current_user_impression = impressions.get(user_key) or {}
        for row in current_user_impression.get("relationships", []):
            if isinstance(row, dict):
                target = str(row.get("target_user_id", "")).strip()
                if target:
                    direct_related_ids.add(target)

        for candidate_id, payload in impressions.items():
            for row in payload.get("relationships", []):
                if not isinstance(row, dict):
                    continue
                target = str(row.get("target_user_id", "")).strip()
                if target == user_key:
                    direct_related_ids.add(str(candidate_id))

        ordered_ids: list[str] = []
        if user_key in impressions:
            ordered_ids.append(user_key)
        ordered_ids.extend(
            uid
            for uid in sorted(direct_related_ids)
            if uid in impressions and uid != user_key
        )
        ordered_ids.extend(uid for uid in sorted(impressions) if uid not in ordered_ids)
        return {uid: impressions[uid] for uid in ordered_ids}

    # ── 最近消息滑动窗口 ──────────────────────────────

    @staticmethod
    def _recent_window_seconds() -> float:
        return float(RECENT_MESSAGE_LIMIT) * 60.0

    def _prune_recent_messages(
        self,
        recent: deque[tuple[float, str]],
        now_ts: float | None = None,
    ) -> None:
        current_ts = time.time() if now_ts is None else now_ts
        cutoff = current_ts - self._recent_window_seconds()
        while recent and recent[0][0] < cutoff:
            recent.popleft()

    def _append_recent_message(
        self,
        recent: deque[tuple[float, str]],
        message_line: str,
    ) -> None:
        now_ts = time.time()
        self._prune_recent_messages(recent, now_ts=now_ts)
        recent.append((now_ts, message_line))

    def _get_recent_lines(self, recent: deque[tuple[float, str]]) -> list[str]:
        self._prune_recent_messages(recent)
        return [line for _, line in recent]

    # ── 日记定时调度 ──────────────────────────────────

    @staticmethod
    def _seconds_until_next_diary_run() -> float:
        now = datetime.now()
        next_run = now.replace(
            hour=DIARY_RUN_HOUR,
            minute=DIARY_RUN_MINUTE,
            second=0,
            microsecond=0,
        )
        if next_run <= now:
            next_run += timedelta(days=1)
        return (next_run - now).total_seconds()

    async def _diary_scheduler_loop(self) -> None:
        """后台循环：每天定时执行日记作业。"""
        while True:
            wait_seconds = self._seconds_until_next_diary_run()
            logger.info(
                "PolarisAgent: 日记调度器等待 %.0f 秒 (下次 %02d:%02d)",
                wait_seconds,
                DIARY_RUN_HOUR,
                DIARY_RUN_MINUTE,
            )
            await asyncio.sleep(wait_seconds)

            try:
                result = await run_diary_job(
                    history_path=self._history_path,
                    soul_path=self._soul_path,
                    diary_dir=self._diary_dir,
                    impression_dir=self._impression_dir,
                    archive_dir=self._archive_dir,
                )
                logger.info(
                    "PolarisAgent: 日记作业完成 date=%s impressions=%s path=%s",
                    result.get("date"),
                    result.get("impression_count"),
                    result.get("diary_path"),
                )
            except Exception:
                logger.exception("PolarisAgent: 日记作业失败")

            # 短暂休眠避免秒级重复触发
            await asyncio.sleep(60)
