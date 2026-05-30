from __future__ import annotations

import argparse
from typing import NoReturn


class _ConsoleArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError(message)
