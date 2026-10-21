"""本地多文件插件拥有独立包上下文，重载不会复用旧的内部模块。"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from aurora_bot.kernel import DirectorySource, compose
from tests.kernel.support import Settings as _Settings

if TYPE_CHECKING:
    from pathlib import Path

_ENTRY = '''"""使用同包服务的插件入口。"""

from aurora_bot.kernel import ModuleManifest, module
from .service import VALUE


@module(name="example", provides=str, manifest=ModuleManifest({version!r}, namespace="lab"))
def build(context):
    """提供实际从同包模块读取的值。"""
    return VALUE


MODULE = build
'''


def _package(root: Path, *, version: str = "1") -> Path:
    """创建真正的入口、同级模块和嵌套子包。"""
    package = root / "example"
    helpers = package / "helpers"
    helpers.mkdir(parents=True, exist_ok=True)
    (package / "module.py").write_text(_ENTRY.format(version=version), encoding="utf-8")
    (package / "service.py").write_text("from .helpers.value import VALUE\n", encoding="utf-8")
    (helpers / "__init__.py").write_text("", encoding="utf-8")
    (helpers / "value.py").write_text('VALUE = "first"\n', encoding="utf-8")
    return package


def test_directory_plugin_imports_siblings_and_nested_subpackages(tmp_path: Path) -> None:
    """不需要安装 Python 包，也不需要修改项目导入路径。"""
    _package(tmp_path)
    specs = tuple(DirectorySource(tmp_path).discover())
    assert len(specs) == 1
    assert specs[0].module_id == "lab:kernel/module/example"
    assert compose(_Settings(), specs).get(str) == "first"


def test_reloading_a_package_uses_new_entry_and_new_internal_modules(tmp_path: Path) -> None:
    """新发布声明不能意外配上旧 sys.modules 中的服务实现。"""
    package = _package(tmp_path)
    original = tuple(DirectorySource(tmp_path).discover())
    assert compose(_Settings(), original).get(str) == "first"
    (package / "module.py").write_text(_ENTRY.format(version="2.0.0"), encoding="utf-8")
    (package / "helpers" / "value.py").write_text('VALUE = "second release"\n', encoding="utf-8")
    revised = tuple(DirectorySource(tmp_path).discover())
    assert revised[0].manifest.version == "2.0.0"
    assert revised[0].resource.ref != original[0].resource.ref
    assert compose(_Settings(), revised).get(str) == "second release"


def test_failed_package_import_removes_its_partially_loaded_modules(tmp_path: Path) -> None:
    """修复导入错误后重试时，不能留下半加载的包或沿用旧子模块。"""
    package = _package(tmp_path)
    (package / "service.py").write_text(
        'from .helpers.value import VALUE\nraise RuntimeError("服务导入失败")\n', encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="服务导入失败"):
        tuple(DirectorySource(tmp_path).discover())
    assert not any(
        (getattr(module, "__file__", None) or "").startswith(str(package)) for module in tuple(sys.modules.values())
    )
    (package / "service.py").write_text("from .helpers.value import VALUE\n", encoding="utf-8")
    (package / "helpers" / "value.py").write_text('VALUE = "recovered"\n', encoding="utf-8")
    assert compose(_Settings(), DirectorySource(tmp_path).discover()).get(str) == "recovered"


def test_file_and_directory_plugins_have_separate_python_import_roots(tmp_path: Path) -> None:
    """文件名字和目录入口名字相似时，延迟相对导入仍能找到自己的包。"""
    package = _package(tmp_path)
    entry = _ENTRY.format(version="1").replace("from .service import VALUE\n", "")
    entry = entry.replace("    return VALUE", "    from .service import VALUE\n    return VALUE")
    (package / "module.py").write_text(entry, encoding="utf-8")
    expected = 7
    (tmp_path / "example_module.py").write_text(
        "from aurora_bot.kernel import ModuleManifest, module\n"
        '@module(name="example", provides=int, manifest=ModuleManifest(namespace="other"))\n'
        "def build(context):\n"
        f"    return {expected}\n"
        "MODULE = build\n",
        encoding="utf-8",
    )
    assembly = compose(_Settings(), DirectorySource(tmp_path).discover())
    assert assembly.get(str) == "first"
    assert assembly.get(int) == expected
