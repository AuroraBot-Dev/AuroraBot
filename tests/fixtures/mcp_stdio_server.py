"""本机 stdio 故障夹具；只写测试目录，不调用模型或业务服务。"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

root, mode = Path(sys.argv[1]), sys.argv[2]
root.mkdir(parents=True, exist_ok=True)
(root / "pid").write_text(str(os.getpid()))
if mode in ("tree", "orphan", "children"):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
    (root / "child").write_text(str(child.pid))
if mode == "exit":
    sys.exit(7)
if mode == "pollution":
    print("invalid secret-output", flush=True)
    time.sleep(300)
if mode == "oversize":
    sys.stdout.write("x" * (5 * 1024 * 1024))
    sys.stdout.flush()
    time.sleep(300)
if mode == "incomplete":
    sys.stdout.write('{"secret-output":')
    sys.stdout.flush()
    sys.exit(0)
if mode == "hang":
    time.sleep(300)
if mode == "stderr":
    sys.stderr.write("secret-stderr" * 1000000)
    sys.stderr.flush()

for line in sys.stdin:
    request = json.loads(line)
    method = request["method"]
    with (root / "requests").open("a", encoding="utf-8") as requests:
        requests.write(method + "\n")
    if "id" not in request:
        continue
    error = None
    if method == "server/discover":
        if mode == "legacy":
            error = {"code": -32601, "message": "secret-unsupported"}
            result = None
        else:
            result = {"supportedVersions": ["2026-07-28"], "capabilities": {"tools": {}}}
    elif method == "initialize":
        result = {
            "protocolVersion": "2025-11-25",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "local-fixture", "version": "1"},
        }
    elif method == "tools/list":
        result = {"tools": [{"name": "echo", "description": "测试回显", "inputSchema": {"type": "object"}}]}
    elif method == "tools/call":
        if mode == "call_exit":
            sys.exit(8)
        if mode == "call_hang":
            time.sleep(300)
        result = {
            "resultType": "complete",
            "content": [{"type": "text", "text": "你好"}],
            "structuredContent": {
                "cwd": os.getcwd(),
                "argument": sys.argv[3] if len(sys.argv) > 3 else "",
                "environment": os.environ.get("TEST_TOKEN"),
                "inherited": os.environ.get("PRIVATE_HOST_VALUE"),
            },
        }
    else:
        result = {}
    response = {"jsonrpc": "2.0", "id": request["id"]}
    response.update({"error": error} if error else {"result": result})
    print(json.dumps(response, ensure_ascii=False), flush=True)
    if mode == "orphan":
        sys.exit(0)

if mode == "tree":
    time.sleep(300)
