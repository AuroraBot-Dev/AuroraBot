"""验证命名空间分配、数据根约束和文件路径冲突。"""

import pytest
from aurora_core.directories import DataDirectories


def test_paths_are_stable_and_namespaces_are_distinct(tmp_path):
    directories = DataDirectories(tmp_path / "data")
    first = directories.namespace("dev.example")
    second = directories.namespace("dev.other")
    assert first == directories.namespace("dev.example")
    assert first != second
    assert first.is_dir() and second.is_dir()
    assert first.relative_to(directories.root).as_posix() == "namespaces/ns-dev.example"
    assert directories.context_snapshot() == directories.root / "framework" / "ctx.json"
    assert directories.structured_database() == directories.root / "framework" / "structured.sqlite3"


@pytest.mark.parametrize(
    "namespace",
    ["../outside", "C:\\outside", "dev..example"],
)
def test_invalid_namespace_cannot_create_directory(tmp_path, namespace):
    root = tmp_path / "data"
    with pytest.raises(ValueError, match="命名空间"):
        DataDirectories(root).namespace(namespace)
    assert not root.exists()


@pytest.mark.parametrize("namespace", ["con.example", "aux.example", "com1.example"])
def test_namespace_prefix_avoids_windows_reserved_names(tmp_path, namespace):
    directory = DataDirectories(tmp_path).namespace(namespace)
    assert directory.is_dir()
    assert directory.name == f"ns-{namespace}"


def test_file_cannot_be_used_as_namespace_directory(tmp_path):
    parent = tmp_path / "namespaces"
    parent.mkdir()
    (parent / "ns-dev.example").write_text("保留文件", encoding="utf-8")
    with pytest.raises(FileExistsError):
        DataDirectories(tmp_path).namespace("dev.example")


def test_redirected_namespace_is_rejected(tmp_path):
    root = tmp_path / "data"
    namespace_root = root / "namespaces"
    namespace_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = namespace_root / "ns-dev.example"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"当前环境不支持创建符号链接：{error}")
    with pytest.raises(ValueError, match="重定向"):
        DataDirectories(root).namespace("dev.example")
    assert list(outside.iterdir()) == []


def test_root_redirection_after_binding_is_rejected(tmp_path):
    root = tmp_path / "data"
    directories = DataDirectories(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        root.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"当前环境不支持创建符号链接：{error}")
    with pytest.raises(ValueError, match="重定向"):
        directories.context_snapshot()
