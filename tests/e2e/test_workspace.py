"""验证统一安装包可加载各功能包。"""

from importlib import metadata


def test_unified_distribution_dependencies():
    requirements = metadata.requires("aurorabot-ai")
    assert requirements is not None
    for package in ("aurora-bot", "aurora-cli", "aurora-api", "aurora-world[environment]"):
        assert any(requirement.startswith(f"{package}>=") for requirement in requirements)
