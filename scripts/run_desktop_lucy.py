# -*- coding: utf-8 -*-
"""Repo-root launcher: python scripts/run_desktop_lucy.py"""
from __future__ import annotations

import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "companion" / "scripts" / "run_desktop_lucy.py"),
    run_name="__main__",
)
