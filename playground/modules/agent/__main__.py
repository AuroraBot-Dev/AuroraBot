"""独立用例入口：python -m playground.modules.agent case.json --record record.json。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from playground.modules.agent import AgentSession
from playground.modules.agent.case import Case
from playground.modules.agent.records import Archive
from playground.session import reject_constant, validation_failure


async def execute(arguments: argparse.Namespace) -> tuple[dict[str, Any], bool]:
    session = AgentSession()
    if arguments.replay is not None:
        record = Archive.model_validate(
            json.loads(arguments.replay.read_text(encoding="utf-8"), parse_constant=reject_constant)
        )
        result = await session.replay(archive=record.model_dump(mode="json"))
        return result.model_dump(mode="json"), result.matched
    case = Case.model_validate(json.loads(arguments.case.read_text(encoding="utf-8"), parse_constant=reject_constant))
    await session.create(case=case.model_dump(mode="json"))
    try:
        state = await session.run()
    except RuntimeError:
        # 非预期的端口失败同样可检查、可显式记录，而不是丢失现场。
        state = await session.snapshot()
    if arguments.record is not None:
        record = await session.export()
        # 显式导出，拒绝覆盖现存文件；不自动保存或恢复执行状态。
        with arguments.record.open("x", encoding="utf-8") as stream:
            stream.write(record.model_dump_json(indent=2) + "\n")
    return state.model_dump(mode="json"), state.status == "completed"


def main() -> int:
    parser = argparse.ArgumentParser(description="独立运行 Agent 离线用例，或比对已保存的运行记录。")
    parser.add_argument("case", nargs="?", type=Path, help="离线用例 JSON 文件")
    parser.add_argument("--record", type=Path, help="显式保存配置、控制与检查点；包含正文，不覆盖已有文件")
    parser.add_argument("--replay", type=Path, help="离线重跑记录并比对所有检查点，不调用真实工具")
    arguments = parser.parse_args()
    if (arguments.case is None) == (arguments.replay is None):
        parser.error("case 与 --replay 必须且只能提供一个")
    if arguments.replay is not None and arguments.record is not None:
        parser.error("--replay 不能同时使用 --record")
    try:
        output, succeeded = asyncio.run(execute(arguments))
    except ValidationError as error:
        details = validation_failure(error)["error"]["details"]
        sys.stderr.write("Agent 用例校验失败：" + json.dumps(details, ensure_ascii=False) + "\n")
        return 1
    except json.JSONDecodeError as error:
        sys.stderr.write(f"Agent 用例 JSON 无效：第 {error.lineno} 行，第 {error.colno} 列\n")
        return 1
    except (OSError, ValueError, TypeError, RuntimeError) as error:
        sys.stderr.write(f"Agent 工作台失败：{type(error).__name__}\n")
        return 1
    sys.stdout.write(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return 0 if succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
