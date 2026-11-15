"""Vercel 函数入口：/api/health（实际应用见 _app.py）。"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from _app import app  # noqa: F401

__all__ = ["app"]
