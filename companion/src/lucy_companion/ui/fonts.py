# -*- coding: utf-8 -*-
"""Load bundled cute fonts for the desktop pet UI."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QFont, QFontDatabase

# companion/assets/fonts
_FONTS_DIR = Path(__file__).resolve().parents[3] / "assets" / "fonts"

_LOADED = False
# logical role -> preferred family name after registration
_FAMILY: dict[str, str] = {}


def _register(path: Path) -> str | None:
    if not path.exists():
        return None
    fid = QFontDatabase.addApplicationFont(str(path))
    if fid < 0:
        return None
    families = QFontDatabase.applicationFontFamilies(fid)
    return families[0] if families else None


def ensure_fonts() -> dict[str, str]:
    """Register OTFs/TTFs once; return role→family map."""
    global _LOADED, _FAMILY
    if _LOADED:
        return _FAMILY

    # Priority lists: first successful file wins for that role
    plans: dict[str, list[str]] = {
        # Soft rounded CJK — Zen Maru / M+ Rounded / Smiley
        "body": [
            "ZenMaruGothic-Medium.ttf",
            "MPLUSRounded1c-Medium.ttf",
            "SmileySans-Oblique.ttf",
            "SmileySans-Oblique.otf",
        ],
        "body_bold": [
            "MPLUSRounded1c-Bold.ttf",
            "ZenMaruGothic-Medium.ttf",
            "SmileySans-Oblique.ttf",
        ],
        # Latin-friendly rounded for codename badge
        "badge": [
            "Nunito-Bold.ttf",
            "MPLUSRounded1c-Bold.ttf",
            "SmileySans-Oblique.ttf",
        ],
        "ja": [
            "MPLUSRounded1c-Medium.ttf",
            "ZenMaruGothic-Medium.ttf",
            "SmileySans-Oblique.ttf",
        ],
    }
    for role, files in plans.items():
        for name in files:
            fam = _register(_FONTS_DIR / name)
            if fam:
                _FAMILY[role] = fam
                break

    _LOADED = True
    return _FAMILY


def font_for(role: str, point_size: int, *, bold: bool = False) -> QFont:
    ensure_fonts()
    key = role
    if bold and role == "body" and "body_bold" in _FAMILY:
        key = "body_bold"
    family = _FAMILY.get(key) or _FAMILY.get("body")
    fallbacks = {
        "body": "Microsoft YaHei UI",
        "body_bold": "Microsoft YaHei UI",
        "badge": "Segoe UI",
        "ja": "Yu Gothic UI",
    }
    f = QFont(family or fallbacks.get(role, "Microsoft YaHei UI"), point_size)
    if bold:
        f.setBold(True)
    # Prefer bundled face when Qt can resolve it
    if family:
        f.setFamilies([family, fallbacks.get(role, "Microsoft YaHei UI")])
    return f


def fonts_dir() -> Path:
    return _FONTS_DIR
