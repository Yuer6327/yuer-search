"""Vercel 函数入口：/api 与 /api/index（实际应用见 _app.py）。"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from _app import app  # noqa: F401  尝试直接导入会在本地开发时给出明确报错

__all__ = ["app"]
