"""产品回归的显式装配夹具；选择仅生成图，不参与生产配置加载。"""

import tomllib
from dataclasses import replace
from importlib.resources import files
from types import SimpleNamespace
from typing import cast
from weakref import WeakKeyDictionary

import tomli_w
from aurora_config.files import configuration_files
from aurora_core import Id
from aurora_core.components import ComponentDeclaration, ComponentExport, ComponentFactory, InstanceExport
from aurora_core.discovery import Plugin, load_plugins, register_plugins
from aurora_core.lifecycle import Lifecycle
from aurora_core.persistence import ContextPersistence
from aurora_host import AssemblyPlan, Host


class LoadedPersistence(ContextPersistence):
    async def start(self):
        pass


from aurora_model.config import BINDINGS

FIXTURES = WeakKeyDictionary()


def configure_bot(ctx, options):
    FIXTURES[ctx].options = options


def bot_options(ctx):
    return FIXTURES[ctx].options


def ref(instance, export):
    return {"instance": instance, "export": export}


def state(namespace, name):
    return {"key": f"org.aurora.{namespace}:state/{name}", "scope": "instance"}


class BotGraph(SimpleNamespace):
    """直接暴露所选图的资源，供业务回归断言。"""

    @property
    def client(self):
        return self.chat.client if hasattr(self, "chat") else None

    async def activate(self, request):
        return await self.owner.activate(request)


class FixtureHost(Host):
    @property
    def state(self):
        return self.lifecycle.state if self.lifecycle is not None else "created"

    def initialize_fixture(self, plugins, *, secret, options, components):
        self.plugins = plugins
        self.root = self.storage.configuration_directory().parent
        self.options = {}
        self.test_options = options or {}
        self.extra_components = components
        self.secret = secret
        external = {
            key: value
            for resources in self.test_options.get("tool_resources", {}).values()
            for key, value in resources.items()
        }
        if self.test_options.get("compaction_recorder") is not None:
            external["recorder"] = self.test_options["compaction_recorder"]
        self.external = external
        if external:
            factory = ComponentFactory(lambda: external, lambda instance: InstanceExport(resources=instance))
            self.plugins = (
                *self.plugins,
                Plugin(
                    "fixture_resources",
                    (),
                    components={"resources": ComponentExport(factory, ComponentDeclaration(resources=tuple(external)))},
                ),
            )

        self.bot = BotGraph(
            ctx=self.ctx,
            registry=self.registry,
            storage=self.storage,
            hooks=self.hooks,
            world_records=None,
            action_evidence=None,
            self_control=None,
            agent=None,
            defaults=None,
            compaction_recorder=self.test_options.get("compaction_recorder"),
        )
        FIXTURES[self.ctx] = self
        if "aurora_world.records" in [p.name for p in plugins]:
            from aurora_world import WorldRecords

            self.bot.world_records = WorldRecords(self.ctx, self.storage)

    def declaration(self):
        saved = self.root / "config/assembly.toml"
        if not self.options and saved.exists():
            return tomllib.loads(saved.read_text())
        d = tomllib.loads(files("aurora_bot").joinpath("presets/default.toml").read_text())
        options = self.options
        owner = options.get("instance_id", "main")
        ins = d["instances"]
        ins["main"]["states"]["runtime"]["location"]["instance_id"] = owner
        for item in ins.values():
            for binding in item.get("states", {}).values():
                if "location" in binding:
                    binding["location"]["instance_id"] = owner
            if "owner" in item.get("options", {}):
                item["options"]["owner"] = owner
        ins["collection"]["options"]["tools"] = [
            {"id": t["tool"], "config": t.get("config", {})} for t in options.get("tools", [])
        ]
        ins["collection"]["options"]["instance_pattern"] = owner + "/tool/{name}"
        ins["chat"]["options"]["profile"] = "primary"
        configs = {
            ("agent", "model_call/config"): {"streaming": options.get("streaming", True)},
            ("agent", "react/config"): {k: options[k] for k in ("max_iterations",) if k in options},
            ("agent", "react_defaults/config"): {"system_prompt": options.get("system_prompt", "")},
            ("tools", "executor/config"): {"timeout": options.get("tool_timeout", 30)},
        }

        def add(name, plugin, component, phases=(), **values):
            ins[name] = {"plugin": plugin, "component": component, **values}
            if plugin not in d["plugins"]:
                d["plugins"].append(plugin)
            for phase, port in phases:
                d["connections"].append(
                    {
                        "plug": {"instance": name, "id": port},
                        "slot": {"instance": name, "id": "org.aurora.core:lifecycle/" + phase},
                    }
                )

        def phases(group, names):
            return [(n, f"org.aurora.bot:handlers/{group}/{n}") for n in names]

        def enabled(name):
            return options.get(name, {}).get("enabled", False)

        resources = ins["collection"]["resources"].setdefault("tools", {})
        tools = ins["collection"]["options"]["tools"]
        if enabled("notes"):
            from aurora_bot.work_notes import NOTE_TOOLS

            add("notes", "aurora_bot.notes", "notes", options={"owner": owner})
            resources["notes"] = ref("notes", "notes")
            tools += [{"id": str(identity), "config": {}} for identity in NOTE_TOOLS.values()]
        if enabled("actions"):
            from aurora_bot.action_evidence import READ_ACTION

            add(
                "actions",
                "aurora_bot.actions",
                "actions",
                phases("actions", ["prepare", "clean"]),
                options={"owner": owner},
                states={"config": state("bot", "actions/config")},
                depends_on=["configuration"],
            )
            configs[("bot", "actions/config")] = {k: v for k, v in options["actions"].items() if k != "enabled"}
            resources["evidence"] = ref("actions", "evidence")
            tools.append({"id": str(READ_ACTION), "config": {}})
            ins["tools"]["resources"] = {"recorder": ref("actions", "evidence")}
            ins["tools"]["depends_on"].append("actions")
        if enabled("self_control"):
            from aurora_bot.self_control import SELF_TOOLS

            add(
                "control",
                "aurora_bot.self_control",
                "control",
                [(n, f"org.aurora.bot:handlers/self_control/{n}") for n in ["prepare", "start", "clean"]],
                options={"owner": owner},
                resources={"runtime": ref("runtime", "runtime"), "agent": ref("main", "agent")},
                depends_on=["runtime"],
            )
            resources["control"] = ref("control", "control")
            tools += [{"id": str(identity), "config": {}} for identity in SELF_TOOLS.values()]
        if self.bot.world_records is not None:
            add(
                "records",
                "aurora_world.records",
                "records",
                [(n, f"org.aurora.world:handlers/records/{n}") for n in ["prepare", "start", "stop", "clean"]],
                depends_on=["configuration"],
            )
        if self.bot.world_records is not None or enabled("notes") or enabled("actions"):
            view_resources = {
                role: ref(instance, export)
                for role, instance, export in [
                    ("records", "records", "records"),
                    ("notes", "notes", "notes"),
                    ("actions", "actions", "evidence"),
                ]
                if instance in ins
            }
            if options.get("context_view", {}).get("enabled", True):
                add(
                    "view",
                    "aurora_bot.world_view",
                    "view",
                    phases("world_view", ["prepare"]),
                    states={"config": state("bot", "world_view/config")},
                    resources=view_resources,
                    depends_on=["configuration"],
                )
                ins["defaults"]["resources"]["context_view"] = ref("view", "view")
            configs[("bot", "world_view/config")] = {
                k: v for k, v in options.get("context_view", {}).items() if k != "enabled"
            }
        if enabled("archive"):
            from aurora_bot.event_archive import READ_EVENT

            add(
                "archive",
                "aurora_bot.world_view",
                "archive",
                states={"config": state("bot", "world_view/config")},
                resources={"records": ref("records", "records")},
            )
            configs.setdefault(("bot", "world_view/config"), {})["archive_max_chars"] = options["archive"].get(
                "max_chars", 8000
            )
            resources["archive"] = ref("archive", "archive")
            tools.append({"id": str(READ_EVENT), "config": {}})
            if "view" in ins:
                ins["view"]["resources"]["archive"] = ref("archive", "archive")
        if enabled("input_budget"):
            add(
                "budget",
                "aurora_agent.react_defaults",
                "input_budget",
                [("config", "org.aurora.agent:handlers/input_budget/configure")],
                states={"config": state("agent", "input_budget/config")},
                depends_on=["configuration"],
            )
            configs[("agent", "input_budget/config")] = {
                k: v for k, v in options["input_budget"].items() if k != "enabled"
            }
            ins["defaults"]["resources"]["input_budget"] = ref("budget", "input_budget")
        if enabled("context_management"):
            add(
                "compaction",
                "aurora_agent.react_defaults",
                "compaction",
                [("config", "org.aurora.agent:handlers/compaction/configure")],
                states={"config": state("agent", "compaction/config")},
                resources={"chat": ref("chat", "model"), "budget": ref("budget", "input_budget")},
                depends_on=["budget"],
            )
            configs[("agent", "compaction/config")] = {
                k: v for k, v in options["context_management"].items() if k != "enabled"
            }
            ins["defaults"]["resources"]["compactor"] = ref("compaction", "compaction")
            ins["defaults"]["resources"]["tool_observation"] = ref("actions", "observation")
            ins["actions"]["states"]["observation_config"] = state("agent", "compaction/config")
        if self.external:
            add("external", "fixture_resources", "resources")
            for name in self.external:
                if name == "recorder" and "compaction" in ins:
                    ins["compaction"]["resources"]["recorder"] = ref("external", name)
                elif name != "recorder":
                    resources[name] = ref("external", name)
        names = [p.name for p in self.plugins]
        if "aurora_bot.cadence" in names:
            add(
                "cadence",
                "aurora_bot.cadence",
                "cadence",
                phases("cadence", ["prepare", "start", "stop", "clean"]),
                options={"owner": owner},
                resources={"runtime": ref("runtime", "runtime"), "records": ref("records", "records")},
                depends_on=["runtime", "records"],
            )
            if "control" in ins:
                ins["cadence"]["resources"]["control"] = ref("control", "control")
        if "decision_profile" in self.test_options:
            add(
                "choice",
                "aurora_model",
                "choice",
                [(phase, f"org.aurora.model:handlers/choice/{phase}") for phase in ("prepare", "clean")],
                options={"profile": self.test_options["decision_profile"]},
                states={"profiles": state("model", "config")},
                depends_on=["configuration"],
            )
            add(
                "decision_view",
                "aurora_bot.world_view",
                "view",
                phases("world_view", ["prepare"]),
                resources={
                    role: ref(instance, export)
                    for role, instance, export in [
                        ("records", "records", "records"),
                        ("notes", "notes", "notes"),
                        ("actions", "actions", "evidence"),
                    ]
                    if instance in ins
                },
                options={
                    "max_chars": tomllib.loads((self.root / "config/org.aurora.bot/cadence.toml").read_text())[
                        "decision"
                    ].get("max_chars", 12000)
                    - 2048
                },
            )
            ins["cadence"]["resources"].update(choice=ref("choice", "model"), view=ref("decision_view", "view"))
            ins["cadence"]["depends_on"].append("choice")
        if "aurora_world.configuration" in names:
            add(
                "sources",
                "aurora_world.sources",
                "sources",
                [(n, f"org.aurora.world:handlers/sources/{n}") for n in ["prepare", "start", "stop", "clean"]],
                resources={"records": ref("records", "records")},
                depends_on=["records", "cadence" if "cadence" in ins else "runtime"],
            )
            add(
                "world_configuration",
                "aurora_world.configuration",
                "configuration",
                [("config", "org.aurora.world:handlers/sources/configure")],
                resources={"sources": ref("sources", "sources")},
                depends_on=["configuration"],
            )
        d["plugins"] = list(dict.fromkeys([*d["plugins"], *names]))
        for (namespace, name), value in configs.items():
            identity = Id(f"org.aurora.{namespace}:state/{name}")
            self.ctx.set(identity, value)
        return d

    async def start(self, *, configure=None):
        persistence = LoadedPersistence(self.ctx, self.storage.snapshot_store())
        await ContextPersistence.start(persistence)
        if configure is not None:
            configure()
        d = self.declaration()
        if self.ctx.list(key=BINDINGS):
            d["instances"]["chat"]["options"]["profile"] = cast(dict, self.ctx.get(BINDINGS))[
                self.options.get("model_role", "reasoning")
            ]
        plan = AssemblyPlan.parse(d)
        plugins = load_plugins(explicit=self.plugins, enabled=plan.plugins)
        if self.bot.world_records is not None:
            records = self.bot.world_records
            selected = []
            for plugin in plugins:
                if plugin.name == "aurora_world.records":
                    export = plugin.components["records"]
                    factory = replace(export.factory, create=lambda **_: records)
                    plugin = replace(plugin, components={"records": ComponentExport(factory, export.declaration)})
                selected.append(plugin)
            plugins = tuple(selected)
        register_plugins(
            self.registry, (p for p in plugins if not any(e.provider == p.name for e in self.registry.entries()))
        )
        services = {**self.services, "resolve_credential": lambda _: self.secret}
        self.graph = plan.assemble(plugins, services)
        b = self.bot
        for attr, instance in [
            ("agent", "main"),
            ("defaults", "defaults"),
            ("owner", "runtime"),
            ("chat", "chat"),
            ("self_control", "control"),
            ("action_evidence", "actions"),
        ]:
            if instance in self.graph.instances:
                setattr(b, attr, self.graph.instances[instance].instance)
        b.runtime = b.owner.runtime
        if b.self_control is not None and "self_control_timing" in self.test_options:
            timing = self.test_options["self_control_timing"]
            b.self_control.now, b.self_control.sleep = timing.now, timing.sleep
        if "cadence" in self.graph.instances and "cadence_timing" in self.test_options:
            self.graph.instances["cadence"].instance._timing = self.test_options["cadence_timing"]
        if self.extra_components is not None:
            self.mount(self.extra_components(b))
        if "compaction" in self.graph.instances:
            self.graph.instances["compaction"].instance.recorder = b.compaction_recorder
        self.root.joinpath("config").mkdir(parents=True, exist_ok=True)
        (self.root / "config/assembly.toml").write_text(tomli_w.dumps(d))

        def configured_files():
            for source in configuration_files(self.registry, self.root / "config"):
                if self.ctx.list(key=source.spec.state, location={}):
                    source.path.parent.mkdir(parents=True, exist_ok=True)
                    source.path.write_text(tomli_w.dumps(cast(dict, self.ctx.get(source.spec.state))))

        configured_files()
        self.lifecycle = Lifecycle(
            self.ctx,
            self.hooks,
            self.graph.components,
            persistence=persistence,
            storage=self.storage,
            timeout=0.05 if self.test_options.get("short_timeout") else 10,
        )
        await self.lifecycle.start()
