# -*- coding: utf-8 -*-
"""Ensure project root + app/ are on sys.path for unittest discovery."""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP = os.path.join(_ROOT, "app")
for _p in (_APP, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
