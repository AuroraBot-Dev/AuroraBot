"""配置编辑仅保存声明 TOML，校验、并发冲突及重启生效边界。"""

import asyncio
import tomllib

import tomli_w
from aiohttp import ClientSession
from aurora_api.contract import describe_contract
from aurora_api.server import serve
from aurora_bot.assembly_config import CONFIG
from aurora_config import CONFIGURATION
from aurora_config.editor import ConfigurationEndpoint
from aurora_config.editor_contract import describe_configuration
from jsonschema import Draft202012Validator
from test_default_assembly import seed, setup


def test_configuration_http_save_conflict_and_restart(tmp_path):
    async def scenario():
        host, assembly, ctx, registry, _, _, events, _ = setup(tmp_path)
        endpoint = registry.get(CONFIGURATION).target
        assert isinstance(endpoint, ConfigurationEndpoint)
        assert (await endpoint.handle("configurationList", {}))[0] == 503
        await host.start(configure=lambda: seed(ctx))
        try:
            async with (
                serve(registry, keys=[], port=0) as url,
                ClientSession() as client,
                client.post(url + "/configuration/list", json={}) as response,
            ):
                assert response.status == 404
                assert (await response.json())["error"]["code"] == "not_found"
            async with serve(registry, keys=[], endpoints=[CONFIGURATION], port=0) as url, ClientSession() as client:
                contract = describe_contract(extensions=[describe_configuration()])

                async def request(action, data, status=200):
                    async with client.post(url + "/configuration/" + action.lower(), json=data) as response:
                        assert response.status == status
                        body = await response.json()
                    schema = {
                        **contract,
                        "$ref": f"#/$defs/Configuration{action}Response" if status == 200 else "#/$defs/ErrorResponse",
                    }
                    Draft202012Validator(schema).validate(body)
                    assert "runtime-secret" not in str(body) and str(tmp_path) not in str(body)
                    return body.get("result", body.get("error"))

                files = await request("List", {})
                selected = next(item for item in files if item["state"] == str(CONFIG))
                assert not any(item["path"] == "host.toml" for item in files)
                document = await request("Get", {"id": selected["id"]})
                second = await request("Get", {"id": next(item["id"] for item in files if item != selected)})
                before = ctx.get(CONFIG)
                assert assembly.config is not None
                assembled = dict(assembly.config)
                config = tomllib.loads(document["content"])
                config["system_prompt"] = "保存后重启生效"
                content = "# 用户注释保留\n" + tomli_w.dumps(config)
                result = await request("Save", {**document, "content": content})
                assert result == {"id": selected["id"], "restart_required": True}
                assert ctx.get(CONFIG) == before and assembly.config == assembled
                assert events == ["model.created", "tool.created"]
                assert (tmp_path / "config" / selected["path"]).read_text(encoding="utf-8") == content
                assert (await request("Save", document, 409))["code"] == "configuration_conflict"
                assert (await request("Save", second, 409))["code"] == "configuration_conflict"
                current = await request("Get", {"id": selected["id"]})
                for invalid in ('secret = "sensitive-value', "max_iterations = -1", 'api_key = "runtime-secret"'):
                    assert (await request("Save", {**current, "content": invalid}, 400))[
                        "code"
                    ] == "invalid_configuration"
                    assert (await request("Get", {"id": selected["id"]})) == current
                for invalid in ({"id": "../host.toml"}, {"id": "dev.unknown:configs/file"}):
                    await request("Get", invalid, 400 if ".." in invalid["id"] else 404)
                async with client.post(
                    url + "/configuration/list", json={}, headers={"Origin": "http://localhost"}
                ) as response:
                    assert response.status == 403
        finally:
            await host.stop()
        assert (await endpoint.handle("configurationList", {}))[0] == 503
        restored, assembly, ctx, *_ = setup(tmp_path)
        await restored.start()
        try:
            assert assembly.config is not None
            assert assembly.config["system_prompt"] == "保存后重启生效"
            restored_config = ctx.get(CONFIG)
            assert isinstance(restored_config, dict) and restored_config["system_prompt"] == "保存后重启生效"
        finally:
            await restored.stop()

    asyncio.run(scenario())


def test_configuration_validation_and_failed_replace_keep_original(tmp_path, monkeypatch):
    async def scenario():
        host, _, ctx, registry, *_ = setup(tmp_path)
        await host.start(configure=lambda: seed(ctx))
        endpoint = registry.get(CONFIGURATION).target
        assert isinstance(endpoint, ConfigurationEndpoint)
        try:
            _, body = await endpoint.handle("configurationList", {})
            bindings = next(item for item in body["result"] if item["state"].endswith("/bindings"))
            _, body = await endpoint.handle("configurationGet", {"id": bindings["id"]})
            document = body["result"]
            assert (await endpoint.handle("configurationSave", {**document, "content": 'reasoning = "missing"'}))[
                0
            ] == 400
            assert (await endpoint.handle("configurationSave", {**document, "content": "#" * 262145}))[0] == 400

            def fail_replace(*_):
                raise OSError("模拟替换失败")

            with monkeypatch.context() as patch:
                patch.setattr("aurora_config.files.os.replace", fail_replace)
                assert (await endpoint.handle("configurationSave", document))[0] == 500
            assert (await endpoint.handle("configurationGet", {"id": bindings["id"]}))[1]["result"] == document
            assert list((tmp_path / "config").rglob(".aurora-config-*")) == []
        finally:
            await host.stop()

    asyncio.run(scenario())
