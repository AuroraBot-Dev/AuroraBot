"""适用于中英文短文本的确定性词项与哈希向量。"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

_WORDS = re.compile(r"[a-z0-9_]+|[\u3400-\u9fff]", re.IGNORECASE)
_CHINESE = re.compile(r"[\u3400-\u9fff]{2,}")
TEXT_FEATURE_SCHEMA = "words_cjk_bigrams_blake2b_v1"


def text_terms(text: str) -> frozenset[str]:
    """组合完整英文词和中文双字词，不依赖网络词表。"""
    normalized = text.casefold()
    terms = set(_WORDS.findall(normalized))
    for segment in _CHINESE.findall(normalized):
        terms.update(segment[index : index + 2] for index in range(len(segment) - 1))
    return frozenset(terms)


def text_similarity(left: str, right: str) -> float:
    """用词项交集的余弦作为可解释的文本相关性基线。"""
    first, second = text_terms(left), text_terms(right)
    if not first or not second:
        return 0.0
    return len(first & second) / math.sqrt(len(first) * len(second))


def text_vector(text: str, dimensions: int) -> tuple[float, ...]:
    """把词项映射到固定坐标；同样文本跨进程得到相同表示。"""
    if dimensions <= 0:
        raise ValueError("文本向量维数必须为正数")
    counts: Counter[int] = Counter()
    for term in text_terms(text):
        digest = hashlib.blake2b(term.encode(), digest_size=8).digest()
        counts[int.from_bytes(digest, "big") % dimensions] += 1
    norm = math.sqrt(sum(value * value for value in counts.values())) or 1.0
    return tuple(counts[index] / norm for index in range(dimensions))
