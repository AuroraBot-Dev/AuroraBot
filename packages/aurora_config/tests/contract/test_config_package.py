"""验证配置接收方身份及 core 对配置包和校验库的独立性。"""

import subprocess
import sys

from aurora_config import CONFIGS, ConfigSchema, ConfigSpec, ConfigTemplate, config_entries, plugin
from aurora_core.admission import AdmissionStatus, inspect_admissions
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import StateKey
from aurora_core.ids import Id


def test_configuration_declarations_use_public_receiver_and_nonpersistent_state():
    registry = bootstrap()
    registry.register_many(plugin().entries)
    key = Id("dev.config:state/settings")
    identity = Id("dev.config:configs/settings")
    registry.register_many(
        config_entries(identity, ConfigSpec(key, ConfigTemplate("example"), ConfigSchema({})), provider="example")
    )
    assert registry.get(identity).register_to == CONFIGS
    state = registry.get(key).target
    assert isinstance(state, StateKey) and state.persistent is False
    assert (
        next(item for item in inspect_admissions(registry) if item.source == identity).status
        == AdmissionStatus.ACCEPTED
    )


def test_core_five_phases_work_without_configuration_package_or_schema_library():
    script = """
import asyncio
import importlib.abc
import sys

class AbsentConfiguration(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'aurora_config', 'jsonschema', 'aurora_adapter', 'aurora_bot', 'aurora_cli'}:
            raise ModuleNotFoundError(fullname)

sys.meta_path.insert(0, AbsentConfiguration())
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import CONFIG, PREPARE, START, STOP, CLEAN, Lifecycle, install_lifecycle_slots

async def run():
    registry = bootstrap()
    install_lifecycle_slots(registry)
    for phase in (CONFIG, PREPARE, START, STOP, CLEAN):
        assert registry.get(phase).kind == 'hook_slot'
    lifecycle = Lifecycle(Context(registry), HookConnections(registry), [])
    await lifecycle.start()
    await lifecycle.stop()
    assert lifecycle.state == 'stopped'

asyncio.run(run())
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False, timeout=10)
    assert result.returncode == 0, result.stderr
