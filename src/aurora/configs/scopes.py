"""注册并解析 ``config/scopes.toml`` 的域目录。"""

from __future__ import annotations

from aurora.contracts.config import ConfigSpec, TableArrayShape, text_field
from aurorabot.contracts.scope import ScopeCatalog, ScopeDeclaration, ScopeKind


def _parse_kind(value: str) -> ScopeKind:
    try:
        return ScopeKind(value)
    except ValueError as error:
        kinds = "、".join(kind.value for kind in ScopeKind)
        raise ValueError(f"域种类必须是 {kinds} 之一：{value!r}") from error


CONFIG_SPEC = ConfigSpec[ScopeCatalog](
    name="scopes",
    path="config/scopes.toml",
    shape=TableArrayShape(
        path=("scope",),
        fields=(
            text_field("pattern"),
            text_field("kind", transform=_parse_kind),
            text_field("description"),
        ),
        model=ScopeDeclaration,
        container=ScopeCatalog,
    ),
)
