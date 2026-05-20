from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from src.config import Config


def kernel_file(name: str) -> Path:
    return Config.KERNEL_DATA_DIR / name


def load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def save_json_list(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(records, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def next_record_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def move_to_done(source: Path, done_dir: Path) -> Path:
    """将文件从当前目录移动到 done 子目录，自动创建父目录。

    移动后返回目标路径。如果目标文件已存在则覆盖。
    这是系统内「文件消费」的标准操作——节点处理完输入后调用此函数。
    """
    import shutil

    done_dir.mkdir(parents=True, exist_ok=True)
    target = done_dir / source.name
    try:
        source.rename(target)
    except OSError:
        shutil.copy2(source, target)
        source.unlink(missing_ok=True)
    return target


def parse_llm_json(raw: str) -> dict[str, Any] | None:
    """从 LLM 原始输出中提取 JSON 对象。

    依次尝试：直接 JSON 解析、```json 代码块提取、
    首尾花括号匹配。均失败返回 None。
    """
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    # 1) 直接解析
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    # 2) ```json ... ``` 代码块
    import re
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        try:
            result = json.loads(match.group(1))
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
    # 3) 首尾花括号
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            result = json.loads(match.group(0))
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
    return None
