from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

import yaml

from src.platform.application_host import ApplicationHost


def _make_fake_app(
    *,
    tempdirs: list[tempfile.TemporaryDirectory[str]],
    package: str,
    command_name: str,
) -> object:
    tmp = tempfile.TemporaryDirectory()
    tempdirs.append(tmp)
    manifest_path = Path(tmp.name) / "manifest.yaml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "package": package,
                "name": package,
                "version": "0.0.0",
                "brain_version": "",
                "commands": [
                    {
                        "name": command_name,
                        "description": "",
                        "parameters": {},
                        "returns": {},
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    async def handler(self, **_kwargs: object) -> dict[str, object]:
        return {}

    attrs = {
        "manifest_path": lambda self: manifest_path,
        "on_start": lambda self: None,
        "on_stop": lambda self: None,
        "on_tick": lambda self: None,
        command_name: handler,
    }
    app_type = type("FakeApp", (), attrs)
    return app_type()


class ApplicationHostTest(unittest.TestCase):
    def test_registers_commands_from_manifests(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            tempdirs: list[tempfile.TemporaryDirectory[str]] = []
            try:
                await host.register(
                    _make_fake_app(
                        tempdirs=tempdirs,
                        package="im.polaris.diary",
                        command_name="write_diary",
                    )
                )
                await host.register(
                    _make_fake_app(
                        tempdirs=tempdirs,
                        package="im.polaris.clock",
                        command_name="set_alarm",
                    )
                )
                await host.register(
                    _make_fake_app(
                        tempdirs=tempdirs,
                        package="im.polaris.qq",
                        command_name="send_qq_message",
                    )
                )
                commands = host.list_commands()
                self.assertIn("im.polaris.diary.write_diary", commands)
                self.assertIn("im.polaris.clock.set_alarm", commands)
                self.assertIn("im.polaris.qq.send_qq_message", commands)
            finally:
                await host.stop_all()
                for tmp in tempdirs:
                    tmp.cleanup()

        asyncio.run(scenario())

    def test_replace_apps_rebinds_commands_to_new_instance(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            tempdirs: list[tempfile.TemporaryDirectory[str]] = []
            try:
                old_app = _make_fake_app(
                    tempdirs=tempdirs,
                    package="im.polaris.qq",
                    command_name="send_qq_message",
                )
                await host.register(old_app)
                old_spec = next(
                    spec
                    for spec in host.list_command_specs()
                    if spec.name == "im.polaris.qq.send_qq_message"
                )
                self.assertIs(old_spec.handler.__self__, old_app)

                new_app = _make_fake_app(
                    tempdirs=tempdirs,
                    package="im.polaris.qq",
                    command_name="send_qq_message",
                )
                await host.replace_apps([new_app])

                self.assertIs(host.get_app("im.polaris.qq"), new_app)
                new_spec = next(
                    spec
                    for spec in host.list_command_specs()
                    if spec.name == "im.polaris.qq.send_qq_message"
                )
                self.assertIs(new_spec.handler.__self__, new_app)
            finally:
                await host.stop_all()
                for tmp in tempdirs:
                    tmp.cleanup()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
