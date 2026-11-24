# -*- coding: utf-8 -*-
"""Entrypoint: python companion/scripts/run_desktop_lucy.py"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# companion/scripts → companion → repo root
ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("LUCY_ROOT", str(ROOT))
SRC = ROOT / "companion" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lucy_companion.ui.desktop_pet import main

if __name__ == "__main__":
    main()
