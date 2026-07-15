"""Compatibility export; HTTP routing is owned by :mod:`src.dashboard`."""

from src.dashboard.api import create_app

__all__ = ["create_app"]
