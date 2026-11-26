"""配置驱动的默认单 bot 装配；资源在恢复后创建，激活由调用方显式发起。"""

import os
from collections.abc import Callable, Iterable
from copy import deepcopy
from functools import partial
from pathlib import Path
from typing import cast

from aurora_adapter.model import ChatClient, require_capabilities
from aurora_adapter.model.config import BINDINGS, resolve_model
from aurora_adapter.model.config import CONFIG as MODEL_CONFIG
from aurora_adapter.model.contract import ChoiceClient
from aurora_agent.compaction import HistoryCompactor
from aurora_agent.input_budget import ModelInputBudget
from aurora_agent.model import ModelCall
from aurora_agent.react import AgentBusyError, ReActAgent
from aurora_agent.react_defaults import ReActContext, ReActDefaults
from aurora_agent.runtime import AgentRuntime
from aurora_agent.tools import TOOLS, ToolExecutor, ToolInstance, ToolSpec
from aurora_config import ConfigSpec, ConfigTemplate, config_entries
from aurora_control import ExecutionRequest, InstanceStateBinding, StateBinding
from aurora_core import entry_from, hook_handler
from aurora_core.ctx import Context, StateKey
from aurora_core.discovery import Plugin
from aurora_core.hooks import HookConnection, HookConnections
from aurora_core.ids import Id
from aurora_core.lifecycle import CLEAN, PREPARE, START, STOP, LifecycleComponent
from aurora_core.registry import DefinitionRegistry, RegistryEntry
from aurora_core.storage import StorageService
from aurora_world import WorldRecords
from aurora_world.configuration import CONFIGURATION as WORLD_CONFIGURATION
from aurora_world.configuration import configured_sources_component

from .action_evidence import READ_ACTION, ActionEvidence
from .action_evidence import create_reader as create_action_reader
from .action_evidence import entries as action_entries
from .assembly_config import (
    AGENTS,
    BOT_SCHEMA,
    CONFIG,
    MESSAGES,
    RUN,
    WORK,
    BotConfig,
    ToolSelection,
    parse_config,
    validate_json,
)
from .cadence import Cadence
from .cadence.state import CONFIGURATION as CADENCE_CONFIGURATION
from .cadence.timing import CadenceTiming
from .cli import command_entries
from .context_view import BusinessContextView
from .conversation import CONVERSATION, ENDPOINTS, ConversationEndpoint
from .event_archive import READ_EVENT, create_reader
from .event_archive import entries as archive_entries
from .memory import CONFIG as MEMORY_CONFIG
from .memory import configured_store
from .memory.automatic import CompactionMemory
from .operations import RUN_CONTROL, RunOperations
from .self_control import SELF_TOOLS, SelfControl, create_tool
from .self_control import entries as self_control_entries
from .work_notes import NOTE_TOOLS, WorkNotes, tool_selections
from .work_notes import entries as note_entries

ASSEMBLY = Id("org.aurora.bot:assemblies/default")


def environment_credential(reference: str) -> str:
    """默认按环境变量名称解析凭证；仅返回运行期值，不写入任何 ctx 地址。"""
    value = os.environ.get(reference)
    if not value:
        raise ValueError(f"运行期凭证未提供：{reference}")
    return value


class DefaultAssembly:
    """默认装配持有模型和单 bot，并在启用 world 配置时托管所选世界来源。

    components() 同步建立生命周期连接；prepare 在宿主恢复和预配置之后读取配置。
    同一配置的多次装配各自调用工厂，不隐式共享模型实例。工具工厂创建的实例由 bot
    所有者逆序关闭，模型最后关闭，ctx 最终落盘由宿主保证；工厂自身负责返回前的失败清理。

    runtime 提供进程内引导提交、激活及取消，自有任务在工具和模型关闭前收束。
    显式调度也可使用 Lifecycle.run(assembly.activate, request)，以 agent.inbox 写入引导；
    两种调度所有者不能并行使用。显式启用 cadence 时由独立转发组件订阅世界并提交新输入。
    模型配置和绑定变更在下次宿主启动生效。默认状态地址按配置的 bot instance_id 隔离。
    """

    def __init__(
        self,
        *,
        registry: DefinitionRegistry,
        ctx: Context,
        hooks: HookConnections,
        storage: StorageService,
        credential_resolver: Callable[[str], str] = environment_credential,
        instance_id: str = "default",
        additional_tools: Callable[[tuple[ToolSelection, ...]], Iterable[ToolSelection]] | None = None,
        world_component_factory: Callable[..., LifecycleComponent] = configured_sources_component,
        cadence_timing: CadenceTiming | None = None,
        self_control_timing: CadenceTiming | None = None,
    ) -> None:
        if not instance_id:
            raise ValueError("装配实例身份不能为空")
        self.registry, self.ctx, self.hooks, self.storage = registry, ctx, hooks, storage
        self.credential_resolver = credential_resolver
        self.instance_id = instance_id
        self._additional_tools = additional_tools
        self._world_component_factory = world_component_factory
        self._cadence_timing = cadence_timing
        self._self_control_timing = self_control_timing or CadenceTiming()
        self.client: ChatClient | None = None
        self.agent: ReActAgent | None = None
        self.defaults: ReActDefaults | None = None
        self.config: BotConfig | None = None
        self._specs: list[ToolSpec] = []
        self._owned_tools: list[ToolInstance] = []
        self._execution_connections: list[HookConnection] = []
        self._connected = False
        self._accepting = False
        self._executing = False
        self._last_request: ExecutionRequest | None = None
        self.runtime = AgentRuntime(
            get_agent=self._runtime_agent,
            execute=self._activate,
            is_executing=lambda: self._executing,
        )
        self._run_operations: RunOperations | None = None
        self.world_records: WorldRecords | None = None
        self.action_evidence: ActionEvidence | None = None
        self.self_control: SelfControl | None = None
        self.compaction_memory: CompactionMemory | None = None

    def _runtime_agent(self) -> ReActAgent:
        if self.agent is None:
            raise RuntimeError("默认 bot 尚未完成装配")
        return self.agent

    def components(self, *, depends_on: tuple[str, ...] = ()) -> tuple[LifecycleComponent, ...]:
        """返回宿主组件；外部工具发现须列入依赖，先于模型和工具检查完成。"""
        if self._connected:
            raise RuntimeError("装配生命周期已经连接")
        model_owner, bot_owner = f"{self.instance_id}/model", f"{self.instance_id}/bot"
        links = []
        cadence = ()
        records_components = ()
        try:
            for owner, phase, method in (
                (model_owner, PREPARE, self.prepare_model),
                (model_owner, CLEAN, self.clean_model),
                (bot_owner, PREPARE, self.prepare_bot),
                (bot_owner, START, self.start_bot),
                (bot_owner, STOP, self.stop_bot),
                (bot_owner, CLEAN, self.clean_bot),
            ):
                definition = entry_from(method, provider="aurora_bot")
                links.append(
                    self.hooks.connect(phase, definition.id, slot_instance=owner, handler_instance=owner, target=method)
                )
            world = ()
            if any(entry.id in (CADENCE_CONFIGURATION, WORLD_CONFIGURATION) for entry in self.registry.entries()):
                self.world_records = WorldRecords(self.ctx, self.storage)
                records_components = (
                    self.world_records.component(
                        self.hooks, instance_id=f"{self.instance_id}/records", depends_on=(bot_owner,)
                    ),
                )
            if any(entry.id == CADENCE_CONFIGURATION for entry in self.registry.entries()):
                assert self.world_records is not None
                cadence = (
                    Cadence(
                        self.ctx,
                        self.hooks,
                        self.runtime,
                        self.world_records,
                        instance_id=f"{self.instance_id}/cadence",
                        decision_factory=self._create_decision_client,
                        view_factory=self._decision_view,
                        timing=self._cadence_timing,
                        paused=lambda: self.self_control is not None and self.self_control.paused(),
                    ).component(depends_on=(records_components[0].instance_id,)),
                )
            if any(entry.id == WORLD_CONFIGURATION for entry in self.registry.entries()):
                world = (
                    self._world_component_factory(
                        self.ctx,
                        self.hooks,
                        records=self.world_records,
                        instance_id=f"{self.instance_id}/world",
                        depends_on=(cadence[0].instance_id if cadence else records_components[0].instance_id,),
                    ),
                )
        except Exception:
            for component in (*cadence, *records_components):
                self.hooks.disconnect_instance(component.instance_id)
            for link in links:
                self.hooks.disconnect(link)
            raise
        self._connected = True
        return (
            LifecycleComponent(model_owner, depends_on=depends_on),
            LifecycleComponent(bot_owner, depends_on=(model_owner,), stop_accepting=self.stop_accepting),
            *records_components,
            *cadence,
            *world,
        )

    async def _create_decision_client(self, role: str) -> ChoiceClient:
        resolved = resolve_model(self.registry, self.ctx.get(MODEL_CONFIG), self.ctx.get(BINDINGS), role, kind="choice")
        api_key = None if resolved.credential is None else self.credential_resolver(resolved.credential)
        return await resolved.factory(resolved.config, api_key=api_key)

    def _decision_view(self, config: dict) -> BusinessContextView:
        assert self.config is not None
        return BusinessContextView(
            self.world_records,
            {
                "enabled": True,
                "events": True,
                "environment": True,
                "notes": True,
                "actions": True,
                "max_chars": config["max_chars"] - 2048,
            },
            notes=WorkNotes(self.ctx, self.config["instance_id"]) if self.config["notes"]["enabled"] else None,
            actions=self.action_evidence,
            archive_enabled=self.config["archive"]["enabled"],
        )

    @hook_handler("org.aurora.bot:handlers/assembly/prepare_model", slot=PREPARE)
    async def prepare_model(self) -> None:
        self.config = parse_config(self.ctx.get(CONFIG))
        if self._additional_tools is not None:
            additions = self._additional_tools(tuple(deepcopy(self.config["tools"])))
            self.config = parse_config({**self.config, "tools": [*self.config["tools"], *additions]})
        if any(Id(item["tool"]) in NOTE_TOOLS.values() for item in self.config["tools"]):
            raise ValueError("笔记工具通过 notes.enabled 装配，不在 tools 中重复声明")
        if any(Id(item["tool"]) == READ_EVENT for item in self.config["tools"]):
            raise ValueError("归档工具通过 archive.enabled 装配，不在 tools 中重复声明")
        if any(Id(item["tool"]) == READ_ACTION for item in self.config["tools"]):
            raise ValueError("行动证据工具通过 actions.enabled 装配，不在 tools 中重复声明")
        if any(Id(item["tool"]) in SELF_TOOLS.values() for item in self.config["tools"]):
            raise ValueError("自身控制工具通过 self_control.enabled 装配，不在 tools 中重复声明")
        if self.config["self_control"]["enabled"]:
            self.self_control = SelfControl(
                self.ctx,
                self.config["instance_id"],
                self.runtime,
                self._runtime_agent,
                now=self._self_control_timing.now,
                sleep=self._self_control_timing.sleep,
            )
            self.self_control.prepare()
            self.config = parse_config(
                {
                    **self.config,
                    "tools": [
                        *self.config["tools"],
                        *(
                            {"tool": str(identity), "instance_id": f"self_control/{action}", "config": {}}
                            for action, identity in SELF_TOOLS.items()
                        ),
                    ],
                }
            )
        if self.config["actions"]["enabled"]:
            self.action_evidence = ActionEvidence(
                self.storage, self.config["instance_id"], max_chars=self.config["actions"]["max_chars"]
            )
            self.config = parse_config(
                {
                    **self.config,
                    "tools": [
                        *self.config["tools"],
                        {"tool": str(READ_ACTION), "instance_id": "actions/read", "config": {}},
                    ],
                }
            )
        if self.config["notes"]["enabled"]:
            self.config = parse_config({**self.config, "tools": [*self.config["tools"], *tool_selections()]})
        if self.config["archive"]["enabled"]:
            if self.world_records is None:
                raise ValueError("archive.enabled 需要显式装配 world 记录服务")
            self.config = parse_config(
                {
                    **self.config,
                    "tools": [
                        *self.config["tools"],
                        {"tool": str(READ_EVENT), "instance_id": "world/read_event", "config": {}},
                    ],
                }
            )
        names: set[str] = set()
        for selection in self.config["tools"]:
            entry = self.registry.get(Id(selection["tool"]))
            if entry.kind != "tool" or entry.register_to != TOOLS or not isinstance(entry.target, ToolSpec):
                raise ValueError("默认装配选择的目标不是工具定义")
            spec = entry.target
            if entry.id in SELF_TOOLS.values():
                assert self.self_control is not None
                action = next(name for name, identity in SELF_TOOLS.items() if identity == entry.id)
                spec = ToolSpec(
                    spec.component, spec.definition, factory=partial(create_tool, action, service=self.self_control)
                )
            if entry.id == READ_EVENT:
                assert self.world_records is not None
                spec = ToolSpec(
                    spec.component,
                    spec.definition,
                    factory=partial(
                        create_reader, records=self.world_records, max_chars=self.config["archive"]["max_chars"]
                    ),
                )
            if entry.id == READ_ACTION:
                assert self.action_evidence is not None
                spec = ToolSpec(
                    spec.component,
                    spec.definition,
                    factory=partial(create_action_reader, evidence=self.action_evidence),
                )
            if spec.factory is None:
                raise ValueError(f"工具未提供实例工厂：{entry.id}")
            if spec.definition["name"] in names:
                raise ValueError("选定工具的模型名称重复")
            names.add(spec.definition["name"])
            self._specs.append(spec)
        resolved = resolve_model(
            self.registry, self.ctx.get(MODEL_CONFIG), self.ctx.get(BINDINGS), self.config["model_role"]
        )
        api_key = None if resolved.credential is None else self.credential_resolver(resolved.credential)
        if api_key is not None and (not isinstance(api_key, str) or not api_key):
            raise ValueError("凭证解析器必须返回非空字符串")
        self.client = await resolved.factory(resolved.config, api_key=api_key)
        require_capabilities(
            self.client,
            {"messages": [], "tools": [spec.definition for spec in self._specs]},
            streaming=self.config["streaming"],
        )

    def _fixed(self, key: Id, part: str | None = None) -> InstanceStateBinding:
        assert self.config is not None
        location = (("instance_id", self.config["instance_id"]),)
        return InstanceStateBinding(key, location if part is None else (*location, ("part", part)))

    def _work(self, part: str) -> StateBinding:
        assert self.config is not None
        return StateBinding(WORK, (("instance_id", self.config["instance_id"]), ("part", part)))

    @hook_handler("org.aurora.bot:handlers/assembly/prepare_bot", slot=PREPARE)
    async def prepare_bot(self) -> None:
        assert self.config is not None and self.client is not None
        identity = self.config["instance_id"]
        if self.action_evidence is not None:
            self.action_evidence.open()
        management = self.config["context_management"]
        budget = (
            ModelInputBudget(self.config["input_budget"]["max_chars"])
            if self.config["input_budget"]["enabled"]
            else None
        )
        if management["enabled"]:
            assert self.action_evidence is not None and budget is not None
            self.action_evidence.max_chars = min(self.action_evidence.max_chars, management["tool_result_chars"] - 512)
        if any(entry.id == MEMORY_CONFIG for entry in self.registry.entries()):
            automatic = self.ctx.get(MEMORY_CONFIG)["auto_compaction"]
            if automatic["enabled"]:
                store, resolved = configured_store(self.ctx, self.storage, identity)

                async def create_embedding():
                    api_key = None if resolved.credential is None else self.credential_resolver(resolved.credential)
                    return await resolved.factory(resolved.config, api_key=api_key)

                self.compaction_memory = CompactionMemory(
                    store,
                    create_embedding,
                    index_timeout_seconds=automatic["index_timeout_seconds"],
                    retry_seconds=automatic["retry_seconds"],
                )
        self.agent = ReActAgent(
            self.ctx,
            self.hooks,
            instance_id=identity,
            inbox=self._fixed(AGENTS, "inbox"),
            progress=self._fixed(AGENTS, "progress"),
            runtime=self._fixed(RUN),
            batch=self._work("batch"),
            decision=self._work("decision"),
            max_iterations=self.config.get("max_iterations"),
        )
        model = ModelCall(
            self.ctx,
            self.client,
            instance_id=f"{identity}/model",
            request_state=self._work("model_input"),
            output_state=self._work("model_output"),
            streaming=self.config["streaming"],
        )
        tools = ToolExecutor(
            self.ctx,
            self.registry,
            self.hooks,
            instance_id=f"{identity}/tools",
            request_state=self._work("tool_calls"),
            output_state=self._work("tool_results"),
            current_state=self._work("tool_current"),
            timeout=self.config["tool_timeout"],
            recorder=self.action_evidence,
        )
        self.defaults = ReActDefaults(
            self.agent,
            model,
            tools,
            context_state=self._fixed(MESSAGES),
            system_prompt=self.config["system_prompt"],
            input_budget=budget,
            compactor=(
                HistoryCompactor(
                    self.client,
                    cast(ModelInputBudget, budget),
                    summary_chars=management["summary_chars"],
                    timeout=management["timeout_seconds"],
                    recorder=self.compaction_memory,
                )
                if management["enabled"]
                else None
            ),
            tool_observation=(
                partial(
                    cast(ActionEvidence, self.action_evidence).observation, max_chars=management["tool_result_chars"]
                )
                if management["enabled"]
                else None
            ),
            context_view=(
                BusinessContextView(
                    self.world_records,
                    self.config["context_view"],
                    notes=WorkNotes(self.ctx, identity) if self.config["notes"]["enabled"] else None,
                    archive_enabled=self.config["archive"]["enabled"],
                    actions=self.action_evidence,
                )
                if self.world_records is not None or self.config["notes"]["enabled"] or self.action_evidence is not None
                else None
            ),
        )
        for selection, spec in zip(self.config["tools"], self._specs, strict=True):
            assert spec.factory is not None
            instance_id = f"{identity}/tool/{selection['instance_id']}"
            input_state, output_state = (
                self._work(f"tool/{selection['instance_id']}/input"),
                self._work(f"tool/{selection['instance_id']}/output"),
            )
            owned = await spec.factory(
                ctx=self.ctx,
                storage=self.storage,
                instance_id=instance_id,
                input_state=input_state,
                output_state=output_state,
                config=selection["config"],
            )
            if not isinstance(owned, ToolInstance):
                raise TypeError("工具工厂必须返回 ToolInstance")
            self._owned_tools.append(owned)
            if (
                owned.plug.instance_id != instance_id
                or owned.plug.states.get("input") != input_state
                or owned.plug.states.get("output") != output_state
            ):
                raise ValueError("工具工厂必须沿用装配分配的实例身份与工作地址")
            link = tools.connect(Id(selection["tool"]), owned.plug)
            self._execution_connections.append(link.connection)
        self.defaults.connect()
        self._execution_connections.extend(
            link.connection
            for phase in ("prepare", "infer", "act", "observe")
            for link in self.agent.slots[phase].links()
        )
        # 恢复出的运行时标志没有对应任务，只保留结果与明确的中断状态。
        for address in (*self.ctx.list(key=RUN, location={"instance_id": identity}), *self.ctx.list(key=WORK)):
            if dict(address.location).get("instance_id") != identity:
                continue
            value = self.ctx.get(address.key, location=dict(address.location))
            if isinstance(value, dict) and value.get("status") == "running":
                self.ctx.set(
                    address.key,
                    {**value, "status": "failed", "error": "InterruptedRun"},
                    location=dict(address.location),
                )

    @hook_handler("org.aurora.bot:handlers/assembly/start_bot", slot=START)
    def start_bot(self) -> None:
        assert self.config is not None
        entry = self.registry.get(RUN_CONTROL)
        if entry.kind != "service" or not isinstance(entry.target, RunOperations):
            raise TypeError("run_control 必须为 RunOperations 服务")
        self.runtime.start()
        if self.compaction_memory is not None:
            self.compaction_memory.start()
        entry.target.bind(self.config["instance_id"], self.runtime)
        self._run_operations = entry.target
        self._accepting = True
        if self.self_control is not None:
            self.self_control.start()

    def stop_accepting(self) -> None:
        self._accepting = False
        if self.self_control is not None:
            self.self_control.stop_accepting()
        self.runtime.stop_accepting()

    async def activate(self, request: ExecutionRequest) -> None:
        """等待一次显式激活，新的引导只写入 inbox；调用方负责结束后的 pending 复查。"""
        if self.runtime.current is not None:
            raise AgentBusyError("运行管理器已接管激活，不能混用调度所有者")
        await self._activate(request)

    async def _activate(self, request: ExecutionRequest) -> None:
        if not self._accepting or self.agent is None:
            raise RuntimeError("默认 bot 未启动或正在关闭")
        if self._executing:
            raise AgentBusyError("默认 bot 正在运行，新引导应写入 inbox")
        self._executing = True
        self._last_request = request
        failure: BaseException | None = None
        try:
            await self.agent.execute(request)
        except BaseException as error:
            failure = error
            raise
        finally:
            try:
                self._compact()
            except BaseException as cleanup_error:
                if failure is not None:
                    raise failure from cleanup_error
                raise
            finally:
                self._executing = False

    def _compact(self) -> None:
        if self.defaults is None or self.agent is None or self.config is None:
            return
        request = self._last_request or ExecutionRequest("maintenance")
        try:
            context = cast(ReActContext, self.defaults.context_state.get(self.ctx, request))
        except KeyError:
            context = {"messages": [], "guidance_sequence": 0, "pending": None}
        keep = set()
        if self._last_request is not None:
            keep.add(self.defaults.model.output_state.address(request))
        else:
            try:
                previous = self.agent.runtime.get(self.ctx, request)
            except KeyError:
                previous = None
            if isinstance(previous, dict) and isinstance(previous.get("run_id"), str):
                keep.add(self.defaults.model.output_state.address(ExecutionRequest(previous["run_id"])))
        if context["pending"] is not None:
            keep.add(self.defaults.tools.output_state.address(ExecutionRequest(context["pending"]["run_id"])))
        for address in self.ctx.list(key=WORK):
            if dict(address.location).get("instance_id") == self.config["instance_id"] and address not in keep:
                self.ctx.delete(address.key, location=dict(address.location))
        self.agent.inbox.set(self.ctx, request, self.agent.pending(request))

    @hook_handler("org.aurora.bot:handlers/assembly/stop_bot", slot=STOP)
    async def stop_bot(self) -> None:
        if self.self_control is not None:
            await self.self_control.close()
        await self.runtime.close()
        if self._executing:
            raise RuntimeError("停止前须通过宿主结束在途激活")
        if self.compaction_memory is not None:
            await self.compaction_memory.stop()
        self._compact()

    @hook_handler("org.aurora.bot:handlers/assembly/clean_bot", slot=CLEAN)
    async def clean_bot(self) -> None:
        if self.self_control is not None:
            await self.self_control.close()
        if self.compaction_memory is not None:
            await self.compaction_memory.close()
            self.compaction_memory = None
        while self._owned_tools:
            owned = self._owned_tools[-1]
            if owned.aclose is not None:
                await owned.aclose()
            self._owned_tools.pop()
        if self.action_evidence is not None:
            self.action_evidence.close()
        for connection in self._execution_connections:
            self.hooks.disconnect(connection)
        self._execution_connections.clear()
        if self._run_operations is not None:
            assert self.config is not None
            self._run_operations.unbind(self.config["instance_id"], self.runtime)
            self._run_operations = None

    @hook_handler("org.aurora.bot:handlers/assembly/clean_model", slot=CLEAN)
    async def clean_model(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None


def assemble(
    *, registry: DefinitionRegistry, ctx: Context, hooks: HookConnections, storage: StorageService, workspace_root: Path
) -> tuple[LifecycleComponent, ...]:
    """宿主兼容的同步装配入口；读取配置和分配资源留到 prepare。"""
    return DefaultAssembly(registry=registry, ctx=ctx, hooks=hooks, storage=storage).components()


def plugin() -> Plugin:
    operations = RunOperations()
    return Plugin(
        "aurora_bot.assembly",
        (
            *command_entries(),
            *note_entries(),
            *archive_entries(),
            *action_entries(),
            *self_control_entries(),
            RegistryEntry(
                CONVERSATION, "endpoint", ConversationEndpoint(operations), "aurora_bot", register_to=ENDPOINTS
            ),
            RegistryEntry(
                ASSEMBLY, "assembly", assemble, "aurora_bot", register_to=Id("org.aurora.core:registries/resources")
            ),
            RegistryEntry(
                RUN_CONTROL,
                "service",
                operations,
                "aurora_bot",
                register_to=Id("org.aurora.core:registries/services"),
            ),
            *(
                entry_from(getattr(operations, name), provider="aurora_bot")
                for name in ("submit", "activate", "cancel")
            ),
            *(
                RegistryEntry(
                    key,
                    "state_key",
                    StateKey(validator),
                    "aurora_bot",
                    register_to=Id("org.aurora.core:registries/state_keys"),
                )
                for key, validator in (
                    (AGENTS, validate_json),
                    (MESSAGES, validate_json),
                    (RUN, validate_json),
                    (WORK, validate_json),
                )
            ),
            *config_entries(
                Id("org.aurora.bot:configs/default"),
                ConfigSpec(CONFIG, ConfigTemplate("aurora_bot"), BOT_SCHEMA),
                provider="aurora_bot",
            ),
            *(
                entry_from(getattr(DefaultAssembly, method), provider="aurora_bot")
                for method in ("prepare_model", "clean_model", "prepare_bot", "start_bot", "stop_bot", "clean_bot")
            ),
        ),
        requires=(
            "aurora_config",
            "aurora_adapter.model",
            "aurora_agent.model",
            "aurora_agent.react",
            "aurora_agent.tools",
            "aurora_agent.react_defaults",
        ),
    )
