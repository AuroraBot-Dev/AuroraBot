"""内建自描述模块经微内核装配的结构与接线测试。"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from src.agents.config import AgentConfig, AgentsConfig
from src.ai.config import EndpointConfig, EndpointsConfig, ProviderConfig, ProvidersConfig
from src.cadence.config import CadenceConfig, ReactionsConfig
from src.contracts.identity import TagsConfig
from src.contracts.pkgs.agents import AgentCatalog
from src.contracts.pkgs.ai import Model
from src.contracts.pkgs.console import TerminalConsole
from src.contracts.pkgs.engine import AgentTreeRunner
from src.contracts.pkgs.mcp import McpRuntime
from src.contracts.pkgs.memory import MemoryReader
from src.contracts.pkgs.prompt import PromptAssembler
from src.contracts.pkgs.tools import ToolRegistry
from src.contracts.pkgs.world import WorldJournal
from src.contracts.scope import ScopeCatalog, ScopeDeclaration, ScopeKind
from src.engine.config import EngineConfig
from src.kernel import BuiltinSource, compose, resolve
from src.mcp.config import AppConfig, AppsConfig, PlatformConfig, PlatformsConfig
from src.memory.config import MemoryConfig
from src.prompt.config import PromptConfig, PromptsConfig
from src.runtime.config import RuntimeConfig
from src.world.config import StorageConfig, StorageEntry

if TYPE_CHECKING:
    from pathlib import Path


class _Settings:
    def __init__(self, project_root: Path, values: dict[type, object]) -> None:
        self._project_root = project_root
        self._values = values

    @property
    def project_root(self) -> Path:
        return self._project_root

    def resolve[T](self, config_type: type[T]) -> T:
        return cast("T", self._values[config_type])


def _settings(tmp_path: Path) -> _Settings:
    prompts = tmp_path / "config" / "prompts"
    prompts.mkdir(parents=True)
    (prompts / "system.txt").write_text("系统提示", encoding="utf-8")
    (prompts / "chat.txt").write_text("会话提示", encoding="utf-8")
    return _Settings(
        tmp_path,
        {
            ProvidersConfig: ProvidersConfig((ProviderConfig("provider", "litellm", "API_KEY"),)),
            EndpointsConfig: EndpointsConfig((EndpointConfig("chat", "provider", "gpt"),)),
            PromptsConfig: PromptsConfig(
                (
                    PromptConfig("aurora:prompt/system/core", "system.txt"),
                    PromptConfig("aurora:prompt/agent/chat", "chat.txt"),
                )
            ),
            AgentsConfig: AgentsConfig(
                (AgentConfig("aurora:agent/chat", "会话", "aurora:prompt/agent/chat", "chat", (), frozenset()),)
            ),
            EngineConfig: EngineConfig(2, 8, 16),
            RuntimeConfig: RuntimeConfig("default", "root", "aurora:agent/chat", "NONE"),
            MemoryConfig: MemoryConfig(60, 10, (), ()),
            CadenceConfig: CadenceConfig(False, "aurora:agent/chat", 5, 3600, 0.25),
            ReactionsConfig: ReactionsConfig(()),
            AppsConfig: AppsConfig(
                (
                    AppConfig(
                        "org.example.app",
                        False,
                        "stdio",
                        "disabled",
                        5.0,
                        working_dir=".",
                        command=("python",),
                    ),
                )
            ),
            PlatformsConfig: PlatformsConfig((PlatformConfig("aurora:platform/mcp", False),)),
            StorageConfig: StorageConfig((StorageEntry("world", "data"),)),
            TagsConfig: TagsConfig(()),
            ScopeCatalog: ScopeCatalog(
                (
                    ScopeDeclaration("aurora:console", ScopeKind.RESOURCE, "终端输入先进入的世界线"),
                    ScopeDeclaration("aurora:tree:*", ScopeKind.RUN, "一次运行的因果台账"),
                )
            ),
        },
    )


def test_builtin_modules_form_a_valid_dependency_graph() -> None:
    specs = tuple(BuiltinSource().discover())
    names = {spec.name for spec in specs}

    assert names == {
        "agents",
        "ai",
        "cadence",
        "console",
        "engine",
        "mcp",
        "memory",
        "prompt",
        "runtime",
        "tools",
        "world",
    }
    resolution = resolve(specs)
    assert resolution.construction[-1].name == "runtime"


def test_builtin_modules_assemble_into_one_assembly(tmp_path: Path) -> None:
    assembly = compose(_settings(tmp_path), BuiltinSource().discover())

    capabilities = (
        assembly.get(Model),
        assembly.get(PromptAssembler),
        assembly.get(AgentCatalog),
        assembly.get(ToolRegistry),
        assembly.get(WorldJournal),
        assembly.get(MemoryReader),
        assembly.get(TerminalConsole),
        assembly.get(McpRuntime),
        assembly.get(AgentTreeRunner),
    )

    assert all(capability is not None for capability in capabilities)
    assert len({id(capability) for capability in capabilities}) == len(capabilities)
