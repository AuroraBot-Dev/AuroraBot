"""记忆存储与工具，资源和所有者由应用显式提供。"""

import hashlib
import json
from dataclasses import asdict
from functools import partial
from importlib.resources import files
from typing import cast

from aurora_config import ConfigSchema, ConfigSpec, ConfigTemplate
from aurora_control import ExecutionPlug, ExecutionRequest, InstanceStateBinding
from aurora_core import plug
from aurora_core.components import ComponentFactory, InstanceExport
from aurora_core.ctx import StateKey
from aurora_tools.execution import ToolInstance, ToolSpec

from ._meta import (
    CLEAN,
    COMPONENT,
    CONFIG,
    CONFIGURATION,
    DELETE,
    EXECUTE,
    PREPARE,
    READ,
    REINDEX,
    SEARCH,
    STORE,
    WRITE,
    memory_plugin,
)
from .contracts import describe_tools
from .store import MemoryStore

MEMORY_TOOLS = dict(
    zip(("write", "search", "read", "delete", "reindex"), (WRITE, SEARCH, READ, DELETE, REINDEX), strict=True)
)


def _check_options(value):
    if value["overlap_chars"] >= value["chunk_chars"]:
        raise ValueError("记忆分块重叠必须小于分块长度")


SCHEMA = ConfigSchema(
    json.loads(files(__package__).joinpath("config.schema.json").read_text(encoding="utf-8")), check=_check_options
)
ARGUMENTS = {action: ConfigSchema(spec["parameters"]) for action, spec in describe_tools().items()}


class MemoryResource:
    """持有 owner 的 SQLite 连接，借用 embedding；模型由提供方关闭。"""

    def __init__(self, ctx, storage, *, instance_id, states, options):
        self.ctx, self.storage = ctx, storage
        self.instance_id, self.states, self.options = instance_id, states, options
        self._store: MemoryStore | None = None
        self.embedding = None

    @property
    def store(self) -> MemoryStore:
        assert self._store is not None
        return self._store

    def bind(self, *, embedding):
        self.embedding = embedding

    @plug(PREPARE)
    def prepare(self):
        binding = self.states["config"]
        options = cast(dict, SCHEMA.parse(self.ctx.get(binding.key, location=dict(binding.location))))
        fingerprint = hashlib.sha256(
            json.dumps({"memory": options, "model": asdict(self.embedding.identity)}, sort_keys=True).encode()
        ).hexdigest()
        self._store = MemoryStore(
            self.storage.directory("org.aurora.memory") / "memory.sqlite3",
            self.options["owner"],
            client=self.embedding,
            fingerprint=fingerprint,
            chunk_chars=options["chunk_chars"],
            overlap_chars=options["overlap_chars"],
        )

    @plug(CLEAN)
    def clean(self):
        if self._store is not None:
            self._store.close()
            self._store = None


class MemoryTool(MemoryResource):
    @plug(EXECUTE)
    async def execute(self, request: ExecutionRequest):
        action = self.options["action"]
        values = dict(self.states["input"].get(self.ctx, request)["arguments"])
        if type(values.get("top_k")) is float and values["top_k"].is_integer():
            values["top_k"] = int(values["top_k"])
        arguments = cast(dict, ARGUMENTS[action].parse(values))
        if action in ("write", "search", "reindex"):
            result = await getattr(self.store, action)(**arguments)
        else:
            result = getattr(self.store, action)(**arguments)
        self.states["output"].set(self.ctx, request, result)

    def execution_plug(self):
        return ExecutionPlug(
            COMPONENT,
            self.execute,
            {role: self.states[role] for role in ("input", "output")},
            instance_id=self.instance_id,
            port_id=EXECUTE,
        )


async def _factory(action, *, ctx, storage, owner, resources, instance_id, input_state, output_state, config):
    tool = MemoryTool(
        ctx,
        storage,
        instance_id=instance_id,
        states={"input": input_state, "output": output_state, "config": InstanceStateBinding(CONFIG)},
        options={"action": action, "owner": owner},
    )
    tool.bind(embedding=resources["embedding"])
    tool.prepare()

    async def close():
        tool.clean()

    return ToolInstance(tool.execution_plug(), close)


def plugin():
    definitions = describe_tools()
    return memory_plugin(
        targets={
            CONFIGURATION: ConfigSpec(CONFIG, ConfigTemplate("aurora_memory"), SCHEMA),
            CONFIG: StateKey(SCHEMA.validate, persistent=False),
            COMPONENT: MemoryTool,
            STORE: MemoryResource,
            **{
                identity: ToolSpec(COMPONENT, definitions[action], factory=partial(_factory, action))
                for action, identity in MEMORY_TOOLS.items()
            },
        },
        components={
            "store": ComponentFactory(
                MemoryResource,
                lambda instance: InstanceExport(
                    plugs={PREPARE: instance.prepare, CLEAN: instance.clean}, resources={"memory": instance}
                ),
                plugs=(MemoryResource.prepare, MemoryResource.clean),
                bind=lambda instance, resources: instance.bind(**resources),
            ),
            "tool": ComponentFactory(
                MemoryTool,
                lambda instance: InstanceExport(
                    plugs={PREPARE: instance.prepare, CLEAN: instance.clean, EXECUTE: instance.execution_plug()}
                ),
                plugs=(MemoryResource.prepare, MemoryResource.clean, MemoryTool.execute),
                bind=lambda instance, resources: instance.bind(**resources),
            ),
        },
    )
