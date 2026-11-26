"""持续巡检工作台：正式世界来源、cadence 与默认 bot 联动。"""

import asyncio
import json
import logging
import math
from contextlib import suppress
from dataclasses import replace
from functools import partial
from typing import cast
from uuid import uuid4

from aurora_adapter.model.config import ADAPTERS, BINDINGS, ModelAdapter
from aurora_adapter.model.config import CONFIG as MODEL_CONFIG
from aurora_adapter.model.plugin import plugin as adapter_plugin
from aurora_adapter.model.testing import FakeModel, FakeReply
from aurora_agent.model import plugin as model_plugin
from aurora_agent.react import plugin as react_plugin
from aurora_agent.react_defaults import ReActContext
from aurora_agent.react_defaults import plugin as defaults_plugin
from aurora_agent.tools import TOOLS, ToolInstance, ToolSpec
from aurora_agent.tools import plugin as tools_plugin
from aurora_bot.assembly import DefaultAssembly
from aurora_bot.assembly import plugin as assembly_plugin
from aurora_bot.assembly_config import AGENTS, CONFIG, MESSAGES, RUN, WORK
from aurora_bot.cadence import plugin as cadence_plugin
from aurora_bot.cadence.state import CHECKPOINT
from aurora_bot.cadence.state import CONFIG_STATE as CADENCE_CONFIG
from aurora_cli.declarations import CONFIG as CLI_CONFIG
from aurora_config import ConfigSpec, ConfigTemplate
from aurora_control import CONTROL_STATE, ExecutionPlug, component_entries
from aurora_control import plugin as control_plugin
from aurora_core import Id, entry_from, hook_handler
from aurora_core.ctx import StateKey
from aurora_core.discovery import Plugin
from aurora_core.lifecycle import CLEAN, PREPARE, START, STOP, LifecycleComponent
from aurora_core.registry import RegistryEntry
from aurora_world import RECORDS, SOURCE_STATUS, SOURCES, SourceInstance, SourceSpec
from aurora_world.configuration import CONFIG_STATE as WORLD_CONFIG
from aurora_world.configuration import configured_sources_component
from aurora_world.configuration import plugin as world_configuration_plugin
from aurora_world.plugin import plugin as world_plugin
from pipeline import INSPECT, PIPELINE, STEPS, create_inspector, declared

NAMESPACE = "dev.example.workshop"
ASSEMBLY = Id(f"{NAMESPACE}:assemblies/live")
SETTINGS = Id(f"{NAMESPACE}:state/settings")
WORLD = Id(f"{NAMESPACE}:state/world")
SOURCE = Id(f"{NAMESPACE}:sources/workshop")
FINISH = Id(f"{NAMESPACE}:handlers/finish")
STATUS = Id(f"{NAMESPACE}:state/status")
REPORTS = Id(f"{NAMESPACE}:state/reports")
ADAPTER = Id(f"{NAMESPACE}:adapters/fake")
INSPECT_TOOL = Id(f"{NAMESPACE}:tools/inspect")
REPORT_TOOL = Id(f"{NAMESPACE}:tools/report")
REPORT = Id(f"{NAMESPACE}:handlers/report")
WRITABLE = (SETTINGS, BINDINGS)
EXPOSED = (WORLD, STATUS, REPORTS, PIPELINE, AGENTS, MESSAGES, RUN, WORK, CONTROL_STATE)
WORLD_EXPOSED = (RECORDS, SOURCE_STATUS, CHECKPOINT)
logger = logging.getLogger(__name__)


def settings(value):
    if not isinstance(value, dict) or value.keys() - {"automatic", "interval", "steps", "delay"}:
        raise ValueError("settings 仅接受 automatic、interval、steps、delay")
    result = {"automatic": True, "interval": 8.0, "steps": 3, "delay": 0.3, **value}
    if type(result["automatic"]) is not bool or type(result["steps"]) is not int or not 1 <= result["steps"] <= 20:
        raise ValueError("automatic 必须为布尔值，steps 为 1 至 20 的整数")
    for name, lower, upper in (("interval", 0.5, 3600), ("delay", 0, 2)):
        number = result[name]
        if type(number) not in (int, float) or not math.isfinite(number) or not lower <= number <= upper:
            raise ValueError(f"{name} 必须在 {lower} 至 {upper} 之间")
    return result


def validate_settings(value):
    settings(value)


async def create_model(config, *, api_key=None, ctx=None):
    """确定性模型通过正式工具协议决策；保留一个请求样本，适合长时间演示。"""

    def respond(request):
        del model.requests[:-1]
        waiting, calls, observations = [], {}, []
        for message in request["messages"]:
            if message["role"] == "user":
                try:
                    data = json.loads(message["content"])
                except (ValueError, TypeError):
                    data = {"text": message["content"]}
                if not isinstance(data, dict):
                    data = {"text": message["content"]}
                if data.get("kind") in ("business_context", "input_budget"):
                    continue
                current = settings(ctx.get(SETTINGS)) if ctx is not None else settings({})
                waiting.append(
                    {"job_id": uuid4().hex, "steps": current["steps"], "delay": current["delay"], "fail": False, **data}
                )
            elif message["role"] == "assistant":
                for call in message.get("tool_calls", []):
                    calls[call["id"]] = call
                    if call["name"] == "inspect":
                        for index, job in enumerate(waiting):
                            if job["text"] == call["arguments"]["text"]:
                                waiting.pop(index)
                                break
            elif message["role"] == "tool":
                observations.append(json.loads(message["content"]))
        reported = {call["arguments"]["source"] for call in calls.values() if call["name"] == "publish_report"}
        pending = [item for item in observations if item["name"] == "inspect" and item["call_id"] not in reported]
        if pending:
            return FakeReply(
                ("正在整理巡检结果。",),
                tuple(
                    {
                        "id": uuid4().hex,
                        "name": "publish_report",
                        "arguments": {
                            "source": item["call_id"],
                            "text": calls[item["call_id"]]["arguments"]["text"],
                            "result": item,
                        },
                    }
                    for item in pending
                ),
            )
        if waiting:
            return FakeReply(
                ("已接纳任务，", "开始分步巡检。"),
                tuple({"id": uuid4().hex, "name": "inspect", "arguments": job} for job in waiting),
            )
        return FakeReply((config.model, "：本次巡检结束，等待新的环境变化或任务。"))

    model = FakeModel(respond, delay=0.05 if config.model == "fast" else 0.2)
    logger.info("已创建离线模型 %s", config.model)
    return model


async def create_reporter(*, ctx, storage, instance_id, input_state, output_state, config):
    async def execute(request):
        arguments = input_state.get(ctx, request)["arguments"]
        try:
            ledger = storage.get(NAMESPACE, "reports")
        except KeyError:
            ledger = {"total": 0, "recent": []}
        record = {**arguments, "run_id": request.run_id}
        ledger = {"total": ledger["total"] + 1, "recent": [*ledger["recent"], record][-10:]}
        # SQLite 台账是报告的持久化来源，ctx 提供可观察视图。
        storage.set(NAMESPACE, "reports", ledger)
        ctx.set(REPORTS, ledger)
        output_state.set(ctx, request, {"published": ledger["total"]})
        logger.info("报告 #%s：%s（%s）", ledger["total"], arguments["text"], arguments["result"]["status"])

    return ToolInstance(
        ExecutionPlug(REPORT, execute, {"input": input_state, "output": output_state}, instance_id=instance_id)
    )


class Workshop:
    """模拟来源与观察视图；引导和激活由正式 cadence、conversation 及 runtime 持有。"""

    def __init__(self, registry, ctx, hooks, storage):
        self.ctx, self.hooks, self.storage = ctx, hooks, storage
        self.bot = DefaultAssembly(
            registry=registry,
            ctx=ctx,
            hooks=hooks,
            storage=storage,
            world_component_factory=partial(
                configured_sources_component, source_factories={SOURCE: self.create_source}
            ),
        )
        self.changed = asyncio.Event()
        self.subscription = None
        self.finish_link = None

    @hook_handler(f"{NAMESPACE}:handlers/prepare", slot=PREPARE)
    def prepare(self):
        try:
            initial = self.ctx.get(CLI_CONFIG)
        except KeyError:
            initial = {}
        for key, value in {
            SETTINGS: settings(initial),
            WORLD: {"tick": 0, "temperature": 20},
            STATUS: {"activations": 0, "status": "idle"},
        }.items():
            try:
                self.ctx.get(key)
            except KeyError:
                self.ctx.set(key, value)
        try:
            ledger = self.storage.get(NAMESPACE, "reports")
        except KeyError:
            ledger = {"total": 0, "recent": []}
        self.ctx.set(REPORTS, ledger)
        for key in (PIPELINE, CONTROL_STATE):
            for address in self.ctx.list(key=key):
                self.ctx.delete(key, location=dict(address.location))

    @hook_handler(f"{NAMESPACE}:handlers/start_observer", slot=START)
    def start_observer(self):
        assert self.bot.agent is not None
        self.finish_link = self.bot.agent.slots["finish"].connect(
            ExecutionPlug(FINISH, self.finish, instance_id="workshop/retention")
        )
        self.subscription = self.ctx.subscribe(self.observe)
        self.ctx.set(STATUS, {**self.ctx.get(STATUS), "status": "idle"})

    def observe(self, change):
        if change.address.key == SETTINGS:
            self.changed.set()
        elif change.address.key == RUN and change.action == "set":
            previous = self.ctx.get(STATUS)
            value = change.value
            self.ctx.set(
                STATUS,
                {
                    "activations": previous["activations"] + int(previous.get("run_id") != value["run_id"]),
                    "status": value["status"],
                    "run_id": value["run_id"],
                },
            )

    async def finish(self, request):
        assert self.bot.defaults is not None
        context = cast(ReActContext, self.bot.defaults.context_state.get(self.ctx, request))
        # 最近一组引导连同完整工具往返保留；未收束轮次由默认策略负责恢复。
        start = max(index for index, message in enumerate(context["messages"]) if message["role"] == "user")
        while start and context["messages"][start - 1]["role"] == "user":
            start -= 1
        messages = context["messages"]
        while start:
            results = {message.get("tool_call_id") for message in messages[start:] if message["role"] == "tool"}
            calls = {call["id"] for message in messages[start:] for call in message.get("tool_calls", [])}
            if results <= calls:
                break
            start -= 1
            while start and messages[start]["role"] != "user":
                start -= 1
        self.bot.defaults.context_state.set(
            self.ctx,
            request,
            {
                **context,
                "messages": messages[start:],
                "exchange_ends": [end - start for end in context.get("exchange_ends", []) if end > start],
            },
        )

    async def create_source(self, *, source_id, emit, config):
        if config:
            raise ValueError("巡检来源参数通过 settings 状态管理")

        async def noop():
            pass

        async def produce():
            while True:
                current = settings(self.ctx.get(SETTINGS))
                tick = self.ctx.get(WORLD)["tick"] + 1
                self.ctx.set(WORLD, {"tick": tick, "temperature": 20 + tick % 9})
                if current["automatic"]:
                    identity = uuid4().hex
                    emit(
                        message_id=identity,
                        payload={
                            "job_id": identity,
                            "text": f"自动巡检 #{tick}",
                            "steps": current["steps"],
                            "delay": current["delay"],
                            "fail": False,
                        },
                    )
                self.changed.clear()
                with suppress(TimeoutError):
                    await asyncio.wait_for(self.changed.wait(), current["interval"])

        return SourceInstance(start=noop, stop=noop, aclose=noop, run=produce)

    @hook_handler(f"{NAMESPACE}:handlers/stop_observer", slot=STOP)
    def stop_observer(self):
        if self.subscription is not None:
            self.ctx.unsubscribe(self.subscription)
            self.subscription = None

    @hook_handler(f"{NAMESPACE}:handlers/clean_observer", slot=CLEAN)
    def clean_observer(self):
        self.stop_observer()
        if self.finish_link is not None:
            assert self.bot.agent is not None
            self.hooks.disconnect(self.finish_link.connection)
            self.finish_link = None


async def declared_source(*, source_id, emit, config):
    raise RuntimeError("巡检来源需要示例装配注入业务环境")


def assemble(*, registry, ctx, hooks, storage, workspace_root):
    entry = registry.get(INSPECT_TOOL)
    registry.replace(
        replace(
            entry,
            target=ToolSpec(INSPECT, entry.target.definition, factory=partial(create_inspector, registry=registry)),
        )
    )
    registry.replace(replace(registry.get(ADAPTER), target=ModelAdapter("chat", partial(create_model, ctx=ctx))))
    app = Workshop(registry, ctx, hooks, storage)
    for owner, phase, method in (
        ("workshop/settings", PREPARE, app.prepare),
        ("workshop/observer", START, app.start_observer),
        ("workshop/observer", STOP, app.stop_observer),
        ("workshop/observer", CLEAN, app.clean_observer),
    ):
        definition = entry_from(method, provider=NAMESPACE)
        hooks.connect(phase, definition.id, slot_instance=owner, handler_instance=owner, target=method)
    components = app.bot.components(depends_on=("workshop/settings",))
    return (
        LifecycleComponent("workshop/settings"),
        *(
            replace(component, depends_on=(*component.depends_on, "workshop/observer"))
            if component.instance_id == "default/world"
            else component
            for component in components
        ),
        LifecycleComponent("workshop/observer", depends_on=("default/bot",)),
    )


def plugins(*, with_world=True):
    tool_schema = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "text": {"type": "string"},
            "fail": {"type": "boolean"},
            "steps": {"type": "integer", "minimum": 1, "maximum": 20},
            "delay": {"type": "number", "minimum": 0, "maximum": 2},
        },
        "required": ["job_id", "text", "fail", "steps", "delay"],
        "additionalProperties": False,
    }
    example = Plugin(
        NAMESPACE,
        (
            RegistryEntry(ASSEMBLY, "assembly", assemble, NAMESPACE),
            RegistryEntry(ADAPTER, "adapter", ModelAdapter("chat", create_model), NAMESPACE, register_to=ADAPTERS),
            RegistryEntry(SOURCE, "source", SourceSpec(declared_source), NAMESPACE, register_to=SOURCES),
            *(
                RegistryEntry(key, "state_key", StateKey(validator), NAMESPACE)
                for key, validator in (
                    (SETTINGS, validate_settings),
                    (WORLD, None),
                    (STATUS, None),
                    (REPORTS, None),
                    (PIPELINE, None),
                )
            ),
            *(
                entry_from(getattr(Workshop, name), provider=NAMESPACE)
                for name in ("prepare", "start_observer", "stop_observer", "clean_observer")
            ),
            *(
                entry
                for key in (INSPECT, REPORT, FINISH, *(Id(f"{NAMESPACE}:handlers/{name}") for name in STEPS))
                for entry in component_entries(key, declared, declared, provider=NAMESPACE)
            ),
            RegistryEntry(
                INSPECT_TOOL,
                "tool",
                ToolSpec(INSPECT, {"name": "inspect", "description": "分步巡检并计算统计", "parameters": tool_schema}),
                NAMESPACE,
                register_to=TOOLS,
            ),
            RegistryEntry(
                REPORT_TOOL,
                "tool",
                ToolSpec(
                    REPORT,
                    {
                        "name": "publish_report",
                        "description": "将巡检结果发布到报告台账",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "source": {"type": "string"},
                                "text": {"type": "string"},
                                "result": {"type": "object"},
                            },
                            "required": ["source", "text", "result"],
                            "additionalProperties": False,
                        },
                    },
                    factory=create_reporter,
                ),
                NAMESPACE,
                register_to=TOOLS,
            ),
        ),
    )
    selected = (
        adapter_plugin(),
        control_plugin(),
        model_plugin(),
        react_plugin(),
        tools_plugin(),
        defaults_plugin(),
        assembly_plugin(),
        *((world_plugin(), world_configuration_plugin(), cadence_plugin()) if with_world else ()),
        example,
    )
    resources = {
        CONFIG: "bot.toml",
        MODEL_CONFIG: "model/profiles.toml",
        BINDINGS: "model/bindings.toml",
        WORLD_CONFIG: "world.toml",
        CADENCE_CONFIG: "cadence.toml",
    }
    return tuple(
        replace(
            item,
            entries=tuple(
                replace(
                    entry,
                    target=replace(
                        entry.target, template=ConfigTemplate(__name__, "config.tomls/" + resources[entry.target.state])
                    ),
                )
                if isinstance(entry.target, ConfigSpec) and entry.target.state in resources
                else entry
                for entry in item.entries
            ),
        )
        for item in selected
    )
