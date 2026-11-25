"""验证版本事务、工具分派和终端表格边界。"""

import asyncio
import tomllib
from io import StringIO

import pytest
from aurora_cli.commander import run_cli
from aurora_cli.commands import check, donk, help
from aurora_cli.declarations import Command
from aurora_core import Id


def workspace(root):
    (root / "pyproject.toml").write_text(
        '# 根包注释\n[project]\nname = "aurorabot-ai"\nversion = "1.2.3"\n'
        'dependencies = ["aurora-core>=1.2.3"]\n'
        '[tool.uv.workspace]\nmembers = ["packages/core"]\n'
        "[tool.uv.sources]\naurora-core = { workspace = true }\n",
        encoding="utf-8",
    )
    member = root / "packages" / "core"
    member.mkdir(parents=True)
    (member / "pyproject.toml").write_text(
        '[project]\nname = "aurora-core"\nversion = "1.2.3"\ndependencies = []\n', encoding="utf-8"
    )
    return [root / "pyproject.toml", member / "pyproject.toml"]


@pytest.mark.parametrize(("action", "expected"), [("major", "2.0.0"), ("minor", "1.3.0"), ("patch", "1.2.4")])
def test_version_update_preserves_comments_and_internal_constraints(tmp_path, monkeypatch, action, expected):
    paths = workspace(tmp_path)

    def lock(command, *, root, output):
        assert command == ["uv", "lock"]
        assert all(tomllib.loads(path.read_text())["project"]["version"] == expected for path in paths)
        (root / "uv.lock").write_text(expected)
        return 0

    monkeypatch.setattr(donk, "run_process", lock)
    assert donk.execute(action, tmp_path, StringIO()) == 0
    assert (tmp_path / "uv.lock").read_text() == expected
    root_content = paths[0].read_text(encoding="utf-8")
    assert "# 根包注释" in root_content
    assert tomllib.loads(root_content)["project"]["dependencies"] == [f"aurora-core>={expected}"]


@pytest.mark.parametrize("existing_lock", [False, True])
def test_lock_failure_restores_all_original_bytes(tmp_path, monkeypatch, existing_lock):
    paths = workspace(tmp_path)
    before = {path: path.read_bytes() for path in paths}
    lock = tmp_path / "uv.lock"
    if existing_lock:
        lock.write_bytes(b"original lock\r\n")

    def fail(command, *, root, output):
        lock.write_text("partial lock")
        return 9

    monkeypatch.setattr(donk, "run_process", fail)
    with pytest.raises(RuntimeError, match="9"):
        donk.execute("patch", tmp_path, StringIO())
    assert {path: path.read_bytes() for path in paths} == before
    assert lock.read_bytes() == b"original lock\r\n" if existing_lock else not lock.exists()


def test_version_mismatch_is_readable_but_cannot_be_bumped(tmp_path):
    paths = workspace(tmp_path)
    paths[1].write_text(paths[1].read_text().replace("1.2.3", "2.0.0"))
    before = {path: path.read_bytes() for path in paths}
    output = StringIO()
    assert donk.execute("show", tmp_path, output) == 0
    assert "aurora-core: 2.0.0" in output.getvalue()
    with pytest.raises(ValueError, match="一致"):
        donk.execute("minor", tmp_path, output)
    assert {path: path.read_bytes() for path in paths} == before


def test_help_preserves_plugin_description_as_literal_text():
    output = StringIO()
    help.execute([Command(Id("dev.test:commands/demo"), "[red]原样[/red]", None, ())], output)
    result = output.getvalue()
    assert "[red]原样[/red]" in result
    assert "\x1b" not in result
    assert "dev.test:commands/demo" in result


@pytest.mark.parametrize(
    "flags", [[], ["--lint", "--fix", "--check"], ["--test"], ["--test", "--full"], ["--coverage"]]
)
def test_check_dispatches_flags_and_preserves_failure_status(tmp_path, monkeypatch, flags):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "check.ts").touch()
    (tmp_path / "package.json").write_text("{}")
    calls = []

    def execute(command, *, root, output):
        calls.append((command, root))
        return 7

    monkeypatch.setattr(check, "run_process", execute)
    status = asyncio.run(run_cli(["--root", str(tmp_path), "check", *flags]))
    assert status == 7
    assert calls == [(["pnpm", "run", "check", *flags], tmp_path)]
