"""控制台参数解析工具 —— 基于 argparse 的轻量封装，遇到错误抛出 ValueError 而非退出进程。

用法::

    from src.localhost.utils import _ConsoleArgumentParser

    parser = _ConsoleArgumentParser(prog="/mytool")
    parser.add_argument("arg1")

作者: [Churk-Ben](https://github.com/Churk-Ben)
"""

from __future__ import annotations

import argparse
from typing import NoReturn


class _ConsoleArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError(message)
