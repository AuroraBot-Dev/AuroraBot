"""进程入口、退出码与错误展示。"""

import asyncio
import logging

from .commander import run_cli


def main() -> int:
    try:
        return asyncio.run(run_cli())
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        # 终端简略模式需要在消息中保留异常类型和详情。
        logging.getLogger(__name__).exception("错误（%s）：%s", type(error).__name__, error)  # noqa: TRY401
        return 1
