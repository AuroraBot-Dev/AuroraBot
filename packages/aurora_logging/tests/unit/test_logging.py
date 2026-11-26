"""验证统一日志的传播、异常记录、轮转及重复配置。"""

import logging
import subprocess
import sys

import aurora_logging
import pytest
from aurora_logging import configure_logging


@pytest.fixture(autouse=True)
def isolate_logging(monkeypatch):
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    for handler in aurora_logging._handlers:
        root.removeHandler(handler)
    monkeypatch.setattr(aurora_logging, "_handlers", [])
    try:
        yield
    finally:
        for handler in aurora_logging._handlers:
            root.removeHandler(handler)
            handler.close()
        root.handlers[:] = handlers
        root.setLevel(level)


def test_import_does_not_configure_logging_or_create_files(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import logging; root = logging.getLogger(); before = (root.handlers[:], root.level); "
                "import aurora_logging; assert (root.handlers, root.level) == before"
            ),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


def test_module_logs_reach_stderr_and_utf8_file_with_independent_levels(tmp_path, capsys):
    configure_logging(log_dir=tmp_path, console_level=logging.INFO, file_level=logging.DEBUG)
    logger = logging.getLogger("aurora_core.logging_test")
    logger.debug("调试详情")
    logger.info("[red]原样日志[/red]")
    output = capsys.readouterr()
    assert output.out == ""
    assert "调试详情" not in output.err
    assert "[red]原样日志[/red]" in output.err
    content = (tmp_path / "aurora.log").read_text(encoding="utf-8")
    assert "DEBUG aurora_core.logging_test 调试详情" in content
    assert "INFO aurora_core.logging_test [red]原样日志[/red]" in content
    assert "\x1b" not in content


@pytest.mark.parametrize("tracebacks", [False, True])
def test_file_keeps_traceback_independently_of_console(tmp_path, capsys, tracebacks):
    configure_logging(log_dir=tmp_path, console_tracebacks=tracebacks)
    try:
        raise ValueError("异常详情")
    except ValueError:
        logging.getLogger("aurora_bot.logging_test").exception("执行失败")
    output = capsys.readouterr()
    assert "执行失败" in output.err
    assert ("ValueError" in output.err) is tracebacks
    content = (tmp_path / "aurora.log").read_text(encoding="utf-8")
    assert "Traceback (most recent call last)" in content
    assert "ValueError: 异常详情" in content


def test_reconfiguration_does_not_duplicate_logs_and_closes_old_file(tmp_path, capsys):
    existing = logging.NullHandler()
    root = logging.getLogger()
    root.addHandler(existing)
    configure_logging(log_dir=tmp_path)
    configure_logging(log_dir=tmp_path)
    logging.getLogger("aurora_core.logging_test").warning("仅记录一次")
    assert capsys.readouterr().err.count("仅记录一次") == 1
    assert (tmp_path / "aurora.log").read_text(encoding="utf-8").count("仅记录一次") == 1
    assert existing in root.handlers

    configure_logging()
    (tmp_path / "aurora.log").unlink()
    logging.getLogger("aurora_core.logging_test").warning("仅终端")
    assert not (tmp_path / "aurora.log").exists()


def test_rotation_bounds_retained_files(tmp_path):
    configure_logging(log_dir=tmp_path, console_level=logging.CRITICAL, max_bytes=128, backup_count=2)
    logger = logging.getLogger("aurora_core.logging_test")
    for index in range(20):
        logger.info("轮转记录 %s %s", index, "x" * 40)
    assert {path.name for path in tmp_path.iterdir()} == {"aurora.log", "aurora.log.1", "aurora.log.2"}
    assert "轮转记录 19" in (tmp_path / "aurora.log").read_text(encoding="utf-8")


def test_file_configuration_failure_preserves_working_handlers(tmp_path, capsys):
    configure_logging()
    blocked = tmp_path / "blocked"
    blocked.write_text("占位", encoding="utf-8")
    with pytest.raises(OSError):
        configure_logging(log_dir=blocked)
    logging.getLogger("aurora_core.logging_test").warning("配置失败仍可输出")
    assert "配置失败仍可输出" in capsys.readouterr().err


@pytest.mark.parametrize("options", [{"max_bytes": 0}, {"backup_count": 0}, {"file_level": -1}])
def test_invalid_configuration_does_not_create_files(tmp_path, options):
    with pytest.raises(ValueError):
        configure_logging(log_dir=tmp_path / "logs", **options)
    assert list(tmp_path.iterdir()) == []
