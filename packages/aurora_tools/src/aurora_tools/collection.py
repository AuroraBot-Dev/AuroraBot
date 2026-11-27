"""按显式选择创建工具实例，借用资源并向宿主发布执行端口。"""

from dataclasses import replace
from fnmatch import fnmatchcase

from aurora_core import Id, plug
from aurora_core.components import InstanceExport

from .execution import ToolPlug
from .plugins.tools._meta import CLEAN, COLLECT


class ToolCollection:
    def __init__(self, ctx, registry, storage, *, instance_id, states, options, publish_members):
        self.ctx, self.registry, self.storage = ctx, registry, storage
        self.instance_id, self.states, self.options = instance_id, states, options
        self.publish_members = publish_members
        self.catalog = None
        self.resources = {}
        self._owned = []

    def bind(self, *, catalog=None, tools):
        self.catalog, self.resources = catalog, tools

    @property
    def tool_ids(self):
        selected = [Id(item["id"]) for item in self.options["tools"]]
        if self.catalog is not None:
            selected.extend(
                identity
                for identity in self.catalog.tool_ids
                if any(fnmatchcase(str(identity), pattern) for pattern in self.options["include"])
                and not any(fnmatchcase(str(identity), pattern) for pattern in self.options["exclude"])
            )
        return tuple(dict.fromkeys(selected))

    def definitions(self):
        return [self.registry.get(identity).target.definition for identity in self.tool_ids]

    async def add(self, identity, spec, *, instance_id, input_state, output_state, resources, config):
        """程序化应用与文件选择共用同一实例创建和资源所有权。"""
        owned = await spec.factory(
            ctx=self.ctx,
            storage=self.storage,
            owner=self.options["owner"],
            resources=resources,
            instance_id=instance_id,
            input_state=input_state,
            output_state=output_state,
            config=config,
        )
        self._owned.append(owned)
        return ToolPlug.from_plug(identity, owned.plug)

    @plug(COLLECT)
    async def prepare(self):
        members = {}
        selections = {Id(item["id"]): item["config"] for item in self.options["tools"]}
        try:
            for identity in self.tool_ids:
                spec = self.registry.get(identity).target
                name = self.options["instance_pattern"].format(
                    collection=self.instance_id, name=spec.definition["name"]
                )
                if name in members:
                    raise ValueError(f"工具集合实例身份重复：{name}")
                states = {
                    role: replace(
                        binding,
                        location=tuple(
                            sorted(dict(binding.location, **{self.options["location_field"]: name}).items())
                        ),
                    )
                    for role, binding in self.states.items()
                }
                port = await self.add(
                    identity,
                    spec,
                    instance_id=name,
                    input_state=states["input"],
                    output_state=states["output"],
                    resources=self.resources,
                    config=selections.get(identity, {}),
                )
                members[name] = InstanceExport(plugs={port.execute_id: port})
            self.publish_members(members)
        except BaseException:
            await self.clean()
            raise

    @plug(CLEAN)
    async def clean(self):
        while self._owned:
            owned = self._owned[-1]
            if owned.aclose is not None:
                await owned.aclose()
            self._owned.pop()
