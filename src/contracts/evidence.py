"""世界证据引用的公共值校验。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


def freeze_evidence_refs(values: Iterable[str]) -> tuple[str, ...]:
    """固定明确来源身份，重复引用不会被当成多份独立证据。"""
    references = tuple(values)
    if any(not isinstance(value, str) or not value.strip() for value in references):
        raise ValueError("证据引用必须是非空世界提交身份")
    return tuple(dict.fromkeys(references))
