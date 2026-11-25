"""本机共享资源验收服务；文件闸门用于观察在途调用和主动断线。"""

import argparse
import asyncio
import json
import os
from pathlib import Path

import uvicorn
from mcp.server import MCPServer
from mcp.server.subscriptions import InMemorySubscriptionBus
from mcp.shared.subscriptions import ResourceUpdated


def service(root: Path) -> MCPServer:
    bus = InMemorySubscriptionBus()
    server = MCPServer("aurora-shared-test", subscriptions=bus)

    @server.resource("test://event")
    def event() -> str:
        """提供固定身份事件，恢复后不自动补发。"""
        return json.dumps({"message_id": "one", "payload": {"text": "共享连接"}}, ensure_ascii=False)

    @server.tool()
    async def probe() -> dict:
        """发送资源提示后等待测试闸门。"""
        with (root / "calls").open("a", encoding="utf-8") as output:
            output.write("probe\n")
        await bus.publish(ResourceUpdated(uri="test://event"))
        (root / "entered").touch()
        try:
            while not (root / "release").exists():
                if (root / "disconnect").exists():
                    os._exit(23)
                await asyncio.sleep(0.01)
            return {"ok": True}
        finally:
            (root / "finished").touch()

    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    (args.root / "pid").write_text(str(os.getpid()), encoding="ascii")
    app = service(args.root)
    if args.port is None:
        app.run()
    else:
        uvicorn.run(app.streamable_http_app(), host="127.0.0.1", port=args.port, log_level="critical")
