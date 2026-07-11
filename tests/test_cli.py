from __future__ import annotations

import argparse
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import Mock, call

from scripts.cli import check, runtime

if TYPE_CHECKING:
    import pytest


def test_check_runs_all_groups_when_both_filters_are_set(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def run(command: list[str]) -> int:
        commands.append(command)
        return 0

    monkeypatch.setattr(check, "run", run)

    assert check.check(argparse.Namespace(lint=True, test=True)) == 0
    assert commands == [*check._LINT_CMDS, *check._TEST_CMDS]


def test_background_server_force_kills_a_stuck_process(monkeypatch: pytest.MonkeyPatch) -> None:
    process = Mock()
    process.wait.side_effect = [subprocess.TimeoutExpired("serve", 5), None]
    kill_tree = Mock()

    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(runtime, "_kill_tree", kill_tree)

    with runtime._background_server():
        pass

    assert kill_tree.call_args_list == [call(process), call(process, force=True)]
    assert process.wait.call_args_list == [call(timeout=5), call()]
