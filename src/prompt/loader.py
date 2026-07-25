"""从 TOML 清单加载不可变提示词目录。"""

from __future__ import annotations

import hashlib
import tomllib
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from src.prompt.models import PromptCatalog, PromptSource

if TYPE_CHECKING:
    from pathlib import Path


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    INVALID_TOP_LEVEL = "prompts.toml must contain exactly system and agent tables"
    INVALID_SYSTEM = "prompts.toml system must contain exactly soul and world"
    INVALID_AGENTS = "prompts.toml agent must be a table"
    MANIFEST_MISSING = "manifest does not exist"
    MANIFEST_INVALID = "manifest is invalid"
    FRAGMENT_MISSING = "fragment does not exist"
    FRAGMENT_ENCODING = "fragment is not UTF-8"
    FRAGMENT_EMPTY = "fragment is empty"
    FRAGMENT_NOT_MARKDOWN = "fragment must be a Markdown file"
    FRAGMENT_REUSED = "prompt fragments must use distinct files"
    STAY_INSIDE_ROOT = "must stay inside the project root"
    STAY_INSIDE_CONFIG = "must stay inside config"
    NON_EMPTY_STRING = "must be a non-empty string"
    PROFILE_MISMATCH = "prompt Agent profiles do not match configured profiles: missing={missing}, extra={extra}"
    PATH_REASON = "prompt path {label} {reason}"
    FILE_ERROR = "prompt {kind}: {path}"


class PromptConfigurationError(ValueError):
    """当提示词清单或其片段无效时抛出。"""

    @classmethod
    def profiles(cls, missing: list[str], extra: list[str]) -> "PromptConfigurationError":
        """Agent 档案与配置文件不匹配时构造错误。"""
        return cls(_Msg.PROFILE_MISMATCH.format(missing=missing, extra=extra))

    @classmethod
    def path(cls, label: str, reason: str) -> "PromptConfigurationError":
        """路径校验失败时构造错误。"""
        return cls(_Msg.PATH_REASON.format(label=label, reason=reason))

    @classmethod
    def file(cls, kind: str, path: Path) -> "PromptConfigurationError":
        """文件操作失败时构造错误。"""
        return cls(_Msg.FILE_ERROR.format(kind=kind, path=path))


def load_prompt_catalog(root: Path, profile_ids: frozenset[str]) -> PromptCatalog:
    """加载提示词目录：解析 TOML 清单，读取所有 Markdown 片段并校验一致性。"""
    root_dir = root.resolve()
    config_dir = (root_dir / "config").resolve()
    if not config_dir.is_relative_to(root_dir):
        raise PromptConfigurationError.path("config", _Msg.STAY_INSIDE_ROOT)
    manifest_path = (config_dir / "prompts.toml").resolve()
    if not manifest_path.is_relative_to(config_dir):
        raise PromptConfigurationError.path("manifest", _Msg.STAY_INSIDE_CONFIG)
    manifest, manifest_source = _read_toml(manifest_path)
    if set(manifest) != {"system", "agent"}:
        raise PromptConfigurationError(_Msg.INVALID_TOP_LEVEL)
    system = manifest["system"]
    agents = manifest["agent"]
    if not isinstance(system, dict) or set(system) != {"soul", "world"}:
        raise PromptConfigurationError(_Msg.INVALID_SYSTEM)
    if not isinstance(agents, dict) or not all(isinstance(key, str) for key in agents):
        raise PromptConfigurationError(_Msg.INVALID_AGENTS)
    configured_profiles = frozenset(agents)
    if configured_profiles != profile_ids:
        missing = sorted(profile_ids - configured_profiles)
        extra = sorted(configured_profiles - profile_ids)
        raise PromptConfigurationError.profiles(missing, extra)

    sources = [manifest_source]
    # soul 允许为空，world 不可为空
    soul, source = _read_fragment(config_dir, system.get("soul"), "system.soul", allow_empty=True)
    sources.append(source)
    world, source = _read_fragment(config_dir, system.get("world"), "system.world")
    sources.append(source)
    agent_prompts: dict[str, str] = {}
    for profile_id, raw_path in sorted(agents.items()):
        content, source = _read_fragment(config_dir, raw_path, f"agent.{profile_id}")
        agent_prompts[profile_id] = content
        sources.append(source)
    # 确保没有两个 Agent 共享同一个 Markdown 片段文件
    fragment_paths = [source.path for source in sources[1:]]
    if len(fragment_paths) != len(set(fragment_paths)):
        raise PromptConfigurationError(_Msg.FRAGMENT_REUSED)
    return PromptCatalog.create(soul=soul, world=world, agents=agent_prompts, sources=tuple(sources))


def _read_toml(path: Path) -> tuple[dict[str, Any], PromptSource]:
    """读取并解析 TOML 文件，返回数据和来源快照。"""
    try:
        raw = path.read_bytes()
    except FileNotFoundError as error:
        raise PromptConfigurationError.file(_Msg.MANIFEST_MISSING, path) from error
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise PromptConfigurationError.file(_Msg.MANIFEST_INVALID, path) from error
    return data, PromptSource(path, hashlib.sha256(raw).hexdigest())


def _read_fragment(
    config_dir: Path, raw_path: object, label: str, *, allow_empty: bool = False
) -> tuple[str, PromptSource]:
    """读取单个 Markdown 提示词片段，校验路径安全和内容有效性。"""
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise PromptConfigurationError.path(label, _Msg.NON_EMPTY_STRING)
    path = (config_dir / raw_path).resolve()
    if not path.is_relative_to(config_dir):
        raise PromptConfigurationError.path(label, _Msg.STAY_INSIDE_CONFIG)
    if path.suffix.lower() != ".md":
        raise PromptConfigurationError.path(label, _Msg.FRAGMENT_NOT_MARKDOWN)
    try:
        raw = path.read_bytes()
        content = raw.decode("utf-8").strip()
    except FileNotFoundError as error:
        raise PromptConfigurationError.file(_Msg.FRAGMENT_MISSING, path) from error
    except UnicodeDecodeError as error:
        raise PromptConfigurationError.file(_Msg.FRAGMENT_ENCODING, path) from error
    if not content and not allow_empty:
        raise PromptConfigurationError.file(_Msg.FRAGMENT_EMPTY, path)
    return content, PromptSource(path, hashlib.sha256(raw).hexdigest())
