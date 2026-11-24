# -*- coding: utf-8 -*-
"""Entrypoint: python companion/scripts/chat_lucy.py"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(r"G:\LIngyuanli\Project\Lucy")
SRC = ROOT / "companion" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lucy_companion.cli import main

if __name__ == "__main__":
    main()
