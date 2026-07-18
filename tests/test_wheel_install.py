from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


def test_installed_wheel_starts_from_an_empty_directory(tmp_path: Path) -> None:
    project_root = Path(__file__).parents[1]
    clean_source = tmp_path / "source"
    clean_source.mkdir()
    for directory in ("aurora", "src"):
        shutil.copytree(project_root / directory, clean_source / directory)
    for filename in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(project_root / filename, clean_source / filename)
    wheel_dir = tmp_path / "dist"
    uv = shutil.which("uv")
    assert uv is not None
    subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(wheel_dir)],
        cwd=clean_source,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(wheel_dir.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    assert not any(name.startswith("scripts/") for name in names)
    assert "src/dashboard/cli.py" not in names
    assert "src/localhost/commands/core.py" not in names
    assert "src/localhost/commands/emit.py" not in names

    installed = tmp_path / "installed"
    subprocess.run(
        [uv, "pip", "install", "--target", str(installed), "--no-deps", str(wheel)],
        check=True,
        capture_output=True,
        text=True,
    )

    empty = tmp_path / "empty"
    empty.mkdir()
    clean_env = {key: value for key, value in os.environ.items() if key != "PYTHONHOME"}
    clean_env["PYTHONPATH"] = str(installed)
    imported = subprocess.run(
        [
            sys.executable,
            "-c",
            "import pathlib, src.contracts.configuration, src.kernel.runtime; "
            "print(pathlib.Path(src.contracts.configuration.__file__).resolve())",
        ],
        cwd=empty,
        env=clean_env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert str(installed.resolve()).lower() in imported.stdout.lower()

    help_result = subprocess.run(
        [sys.executable, "-m", "aurora", "--help"],
        cwd=empty,
        env=clean_env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "AuroraBot CLI" in help_result.stdout

    script = installed / "bin" / ("aurora.exe" if os.name == "nt" else "aurora")
    assert script.is_file()
    script_help = subprocess.run(
        [str(script), "--help"],
        cwd=empty,
        env=clean_env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "AuroraBot CLI" in script_help.stdout
