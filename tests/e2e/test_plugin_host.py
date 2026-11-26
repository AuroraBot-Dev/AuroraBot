"""通过真实发行元数据发现插件，验证可选宿主接入边界。"""

import logging

from aurora_core.admission import AdmissionStatus, inspect_admissions
from aurora_core.bootstrap import KindReceiver, bootstrap
from aurora_core.discovery import load_plugins, register_plugins
from aurora_core.ids import Id
from aurora_core.registry import RegistryEntry


def test_installed_plugin_without_cli_or_api(tmp_path, monkeypatch, caplog):
    module = tmp_path / "aurora_fixture_plugin.py"
    module.write_text(
        """from aurora_core.discovery import Plugin
from aurora_core.ids import Id
from aurora_core.registry import RegistryEntry

def create():
    return Plugin("fixture", (
        RegistryEntry(Id("dev.fixture:resources/prompt"), "resource", "hello", "fixture",
                      register_to=Id("org.aurora.core:registries/resources")),
        RegistryEntry(Id("dev.fixture:commands/chat"), "command", object(), "fixture",
                      register_to=Id("org.aurora.cli:registries/commands")),
        RegistryEntry(Id("dev.fixture:endpoints/chat"), "endpoint", object(), "fixture",
                      register_to=Id("org.aurora.api:registries/endpoints")),
    ))
""",
        encoding="utf-8",
    )
    distribution = tmp_path / "aurora_fixture_plugin-1.0.dist-info"
    distribution.mkdir()
    (distribution / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: aurora-fixture-plugin\nVersion: 1.0\n", encoding="utf-8"
    )
    (distribution / "entry_points.txt").write_text(
        "[aurora.plugins]\nfixture = aurora_fixture_plugin:create\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    registry = bootstrap()
    register_plugins(registry, load_plugins(enabled=["fixture"]))
    with caplog.at_level(logging.WARNING):
        results = inspect_admissions(registry)
    own = [result for result in results if result.provider == "fixture"]
    assert [result.status for result in own] == [
        AdmissionStatus.ACCEPTED,
        AdmissionStatus.UNCONNECTED,
        AdmissionStatus.UNCONNECTED,
    ]
    assert registry.get(Id("dev.fixture:resources/prompt")).target == "hello"
    assert "org.aurora.cli:registries/commands" in caplog.text
    assert "org.aurora.api:registries/endpoints" in caplog.text
    assert len(registry.view(kind="command")) == 1


def test_receiver_registered_after_declaration_and_rejection():
    registry = bootstrap()
    target = Id("dev.example:registries/custom")
    entry = RegistryEntry(Id("dev.example:resources/item"), "resource", object(), "example", register_to=target)
    registry.register(entry)
    registry.register(RegistryEntry(target, "registry", KindReceiver(frozenset({"resource"})), "example"))
    assert inspect_admissions(registry)[-1].status == AdmissionStatus.ACCEPTED
    registry.replace(RegistryEntry(target, "registry", KindReceiver(frozenset({"operation"})), "example"))
    result = inspect_admissions(registry)[-1]
    assert result.status == AdmissionStatus.REJECTED
    assert result.reason is not None
    assert "resource" in result.reason


def test_registration_acceptance_does_not_hide_missing_slot():
    registry = bootstrap()
    registry.register(
        RegistryEntry(
            Id("dev.example:handlers/prepare"),
            "hook_handler",
            object(),
            "example",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            slot=Id("org.aurora.agent:react/prepare"),
        )
    )
    results = inspect_admissions(registry)[-2:]
    assert results[0].status == AdmissionStatus.ACCEPTED
    assert results[1].status == AdmissionStatus.UNCONNECTED


def test_slot_owns_compatibility_without_schema_equality():
    class CompatibleSlot:
        def rejection_reason(self, entry):
            return None if entry.interface in (None, "可接受的另一种描述") else "接口不兼容"

    registry = bootstrap()
    slot = Id("dev.example:slots/prepare")
    registry.register(RegistryEntry(slot, "hook_slot", CompatibleSlot(), "example", interface="插槽描述"))
    for name, description in (("plain", None), ("compatible", "可接受的另一种描述"), ("invalid", "其他描述")):
        registry.register(
            RegistryEntry(
                Id(f"dev.example:handlers/{name}"),
                "hook_handler",
                object(),
                "example",
                slot=slot,
                interface=description,
            )
        )
    assert [result.status for result in inspect_admissions(registry)[-3:]] == [
        AdmissionStatus.ACCEPTED,
        AdmissionStatus.ACCEPTED,
        AdmissionStatus.REJECTED,
    ]
