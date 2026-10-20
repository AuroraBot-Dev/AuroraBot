"""将模组声明固定为可检查的资源正文，代码实现仍由安装环境提供。"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from aurorabot.contracts.module_manifest import MODULE_MANIFEST_CONTRACT
from aurorabot.contracts.resource import ResourceDescriptor, ResourceRef
from aurorabot.contracts.resource_codec import resource_data, resource_ref_data

if TYPE_CHECKING:
    from aurorabot.kernel.declaration import ModuleSpec, PhaseHook
    from aurorabot.kernel.phase import Phase


def freeze_module(spec: ModuleSpec) -> tuple[bytes, ResourceDescriptor]:
    """固定完整声明与简明目录说明，定义正文按同一摘要读取。"""
    capabilities = {"provides": _capabilities(spec.provides), "requires": _capabilities(spec.requires)}
    declared = {
        "schema_version": 1,
        "key": spec.module_id,
        "version": spec.manifest.version,
        "kernel_api": spec.manifest.kernel_api,
        **capabilities,
        "contributes": [key.name for key in spec.contributes],
        "consumes": [key.name for key in spec.consumes],
        "declares": [key.name for key in spec.declares],
        "owns_scopes": list(spec.owns_scopes),
        "observes_scopes": list(spec.observes_scopes),
        "scopes": [
            {"pattern": scope.pattern, "kind": scope.kind.value, "description": scope.description}
            for scope in spec.scopes
        ],
        "resources": [resource_data(resource) for resource in spec.resources],
        "priority": spec.priority,
        "optional": spec.optional,
        "lifecycle": [
            {**_phase_data(phase), "hook": _hook_name(hook)}
            for phase, hook in sorted(spec.hooks.items(), key=lambda entry: (entry[0].order, entry[0].name))
        ],
        "ordering": [
            {
                "phase": _phase_data(order.phase),
                "after": _capabilities(order.after),
                "after_phase": _phase_data(order.after_phase) if order.after_phase is not None else None,
            }
            for order in spec.order
        ],
    }
    content = json.dumps(
        declared, default=dict, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    ref = ResourceRef(spec.key, hashlib.sha256(content).hexdigest())
    descriptor = ResourceDescriptor(
        ref,
        "可用模组的发布清单与启动能力声明；正文保留完整资源、域与生命周期约束。",
        MODULE_MANIFEST_CONTRACT,
        {
            "version": spec.manifest.version,
            "kernel_api": spec.manifest.kernel_api,
            "declared_capabilities": capabilities,
            "declared_resources": [resource_ref_data(resource.ref) for resource in spec.resources],
            "read_operation": "aurora:artifacts/query/read",
        },
    )
    return content, descriptor


def _capabilities(values: tuple[type, ...]) -> list[str]:
    """公开契约的 Python 身份用于核对声明，不序列化运行期对象。"""
    return [f"{value.__module__}.{value.__qualname__}" for value in values]


def _phase_data(phase: Phase) -> dict[str, Any]:
    """阶段名称、排序、运行形式与关闭边界都属于声明。"""
    return {"name": phase.name, "order": phase.order, "kind": phase.kind.value, "shutdown": phase.shutdown}


def _hook_name(hook: PhaseHook) -> str:
    """记录钩子来源；实现变化仍需要作者发布新版本。"""
    namespace = getattr(hook, "__module__", type(hook).__module__)
    name = getattr(hook, "__qualname__", type(hook).__qualname__)
    return f"{namespace}.{name}"
