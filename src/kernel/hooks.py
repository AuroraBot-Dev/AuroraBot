"""Hook system for the AuroraBot kernel.

Provides pre/post/error hooks that allow external plugins to intercept
file events and processing lifecycle.

Usage::

    from src.kernel.hooks import hook_registry

    async def audit_hook(event, node):
        logger.info(f"event: {event.path} -> {node.id}")

    hook_registry.register("post_dispatch", audit_hook)
    hook_registry.unregister("post_dispatch", audit_hook)
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from src.utils.log_utils import get_logger

logger = get_logger("Hooks")

HookFunc = Callable[..., Awaitable[None]]


class HookRegistry:
    """Central registry for kernel hooks.

    Hook points:

    - ``pre_assign``: before a file is assigned to a worker.
      Signature: ``(file_meta, route) -> None``
    - ``post_assign``: after a file is assigned to a worker.
      Signature: ``(file_meta, node_id) -> None``
    - ``pre_process``: before a node processes a file.
      Signature: ``(file_meta, node) -> None``
    - ``post_process``: after a node processes a file.
      Signature: ``(file_meta, node, output_meta) -> None``
    - ``pre_dispatch``: before an event is dispatched to nodes.
      Signature: ``(event) -> FileEvent | None``
      Return ``None`` to suppress the event.
    - ``post_dispatch``: after an event is dispatched.
      Signature: ``(event, matched_nodes) -> None``
    - ``on_error``: on a processing error.
      Signature: ``(file_meta, node, exception) -> None``
    """

    def __init__(self) -> None:
        self._hooks: dict[str, list[HookFunc]] = defaultdict(list)

    def register(self, hook_point: str, func: HookFunc) -> None:
        """Register a hook function."""
        if func not in self._hooks[hook_point]:
            self._hooks[hook_point].append(func)
            logger.debug("Hook registered: %s -> %s", hook_point, func.__name__)

    def unregister(self, hook_point: str, func: HookFunc) -> None:
        """Unregister a hook function."""
        try:
            self._hooks[hook_point].remove(func)
            logger.debug("Hook unregistered: %s -> %s", hook_point, func.__name__)
        except ValueError:
            pass

    async def trigger(self, hook_point: str, *args: Any, **kwargs: Any) -> list[Any]:
        """Trigger all hooks for a given hook point.

        Returns a list of results (for ``pre_dispatch``, None results
        signal event suppression).
        """
        results: list[Any] = []
        for hook in list(self._hooks[hook_point]):
            try:
                result = await hook(*args, **kwargs)
                results.append(result)
            except Exception:
                logger.exception("Hook %s failed at %s", hook.__name__, hook_point)
        return results

    def trigger_sync(self, hook_point: str, *args: Any, **kwargs: Any) -> list[Any]:
        """Trigger all hooks synchronously for non-async contexts."""
        results: list[Any] = []
        for hook in list(self._hooks[hook_point]):
            try:
                result = hook(*args, **kwargs)
                if isinstance(result, Awaitable):
                    logger.warning("Hook %s is async but called synchronously", hook.__name__)
                results.append(result)
            except Exception:
                logger.exception("Hook %s failed at %s", hook.__name__, hook_point)
        return results

    def clear(self) -> None:
        """Remove all hooks."""
        self._hooks.clear()


# Module-level singleton
hook_registry = HookRegistry()
