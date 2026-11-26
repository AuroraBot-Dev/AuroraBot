"""声明配置文件的共同定位、校验与显式保存；保存不改变运行期 ctx。"""

import hashlib
import json
import os
import tempfile
import tomllib
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from aurora_core.ctx import StateAddress, StateKey, StateRecord
from aurora_core.ids import Id
from aurora_core.registry import DefinitionRegistry

from .declarations import CONFIGS, ConfigReceiver, ConfigSpec
from .templates import checked_path, copy_missing, read_toml


@dataclass(frozen=True)
class ConfigFile:
    identity: Id
    spec: ConfigSpec
    path: Path


def configuration_files(registry: DefinitionRegistry, directory: Path) -> tuple[ConfigFile, ...]:
    root = directory.resolve()
    sources = []
    destinations: set[str] = set()
    states: set[Id] = set()
    for entry in registry.view(register_to=CONFIGS):
        reason = ConfigReceiver().rejection_reason(entry)
        if reason is not None:
            raise ValueError(f"{entry.id}：{reason}")
        spec = entry.target
        assert isinstance(spec, ConfigSpec)
        state = registry.get(spec.state)
        if state.kind != "state_key" or not isinstance(state.target, StateKey) or state.target.persistent:
            raise ValueError(f"配置目标必须为非持久状态：{spec.state}")
        template = spec.template
        template.source()
        target = checked_path(
            root / (template.owner or spec.state.namespace) / template.resource.removeprefix("config.tomls/")
        )
        identity = str(target).casefold()
        if identity in destinations or spec.state in states:
            raise ValueError(f"配置目标文件或状态重复：{entry.id}")
        destinations.add(identity)
        states.add(spec.state)
        sources.append(ConfigFile(entry.id, spec, target))
    return tuple(sources)


def validate_configuration(sources: tuple[ConfigFile, ...], values: dict[Id, object]) -> tuple[StateRecord, ...]:
    records = []
    for source in sources:
        try:
            value = source.spec.schema.parse(values[source.spec.state])
        except (ValueError, TypeError) as error:
            raise ValueError(f"配置文件 {source.path}：{error}") from None
        records.append(StateRecord(StateAddress(source.spec.state), value))
    parsed = {record.address.key: record.value for record in records}
    for source in sources:
        if source.spec.check is not None:
            try:
                source.spec.check(deepcopy(parsed))
            except (ValueError, TypeError, KeyError) as error:
                raise ValueError(f"配置文件 {source.path} 的关联校验失败：{error}") from None
    return tuple(records)


def load_configuration(registry: DefinitionRegistry, directory: Path) -> tuple[StateRecord, ...]:
    """全部文件和配置关系通过校验才返回；只生成缺失的用户文件。"""
    sources = configuration_files(registry, directory)
    values = {}
    for source in sources:
        copy_missing(source.path, source.spec.template.source().read_bytes())
        values[source.spec.state] = read_toml(source.path)
    return validate_configuration(sources, values)


class ConfigurationConflict(Exception):
    """读取后的任一声明配置已被修改，须重新读取再编辑。"""


class ConfigurationFiles:
    """同步保存使同一宿主请求串行；修订覆盖全部声明文件以保护关联校验。"""

    def __init__(self, registry: DefinitionRegistry, directory: Path) -> None:
        self.registry, self.directory = registry, directory.resolve()

    def list(self) -> list[dict[str, str]]:
        return [
            {
                "id": str(item.identity),
                "state": str(item.spec.state),
                "path": item.path.relative_to(self.directory).as_posix(),
            }
            for item in configuration_files(self.registry, self.directory)
        ]

    def _snapshot(self) -> tuple[tuple[ConfigFile, ...], dict[Id, bytes], str]:
        sources = configuration_files(self.registry, self.directory)
        contents = {}
        for source in sources:
            with source.path.open("rb") as stream:
                content = stream.read(262145)
            if len(content) > 262144:
                raise ValueError("配置文件超过编辑大小上限")
            contents[source.identity] = content
        fingerprints = sorted((str(key), hashlib.sha256(value).hexdigest()) for key, value in contents.items())
        revision = hashlib.sha256(json.dumps(fingerprints).encode()).hexdigest()
        return sources, contents, revision

    def get(self, identity: Id) -> dict[str, str]:
        _, contents, revision = self._snapshot()
        return {"id": str(identity), "content": contents[identity].decode("utf-8-sig"), "revision": revision}

    def save(self, identity: Id, content: str, revision: str) -> dict:
        sources, contents, current = self._snapshot()
        if identity not in contents:
            raise KeyError(identity)
        if current != revision:
            raise ConfigurationConflict
        candidate = content.encode("utf-8")
        if len(candidate) > 262144:
            raise ValueError("配置文件超过编辑大小上限")
        contents[identity] = candidate
        values = {source.spec.state: tomllib.loads(contents[source.identity].decode("utf-8-sig")) for source in sources}
        validate_configuration(sources, values)
        target = next(source.path for source in sources if source.identity == identity)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".aurora-config-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(candidate)
                stream.flush()
                os.fsync(stream.fileno())
            if self._snapshot()[2] != revision:
                raise ConfigurationConflict
            checked_path(target)
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return {"id": str(identity), "restart_required": True}
