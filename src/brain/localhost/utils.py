from __future__ import annotations

import argparse


class _ConsoleArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)
