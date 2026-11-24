# -*- coding: utf-8 -*-
"""Local image → data-URL for OpenAI-compatible vision chat."""
from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any

_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
}


def encode_image_data_url(
    path: str | Path,
    *,
    max_edge: int = 1280,
    jpeg_quality: int = 85,
) -> str:
    """Resize if needed and return data:image/...;base64,..."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    raw = p.read_bytes()
    mime = _MIME.get(p.suffix.lower(), "image/jpeg")
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        elif img.mode == "L":
            img = img.convert("RGB")
        w, h = img.size
        edge = max(w, h)
        if edge > max_edge and edge > 0:
            scale = max_edge / float(edge)
            img = img.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))),
                Image.Resampling.LANCZOS,
            )
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=int(jpeg_quality), optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        # Pillow missing / decode fail → raw bytes
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:{mime};base64,{b64}"


def multimodal_user_content(
    text: str,
    image_path: str | Path | None = None,
    *,
    max_edge: int = 1280,
) -> str | list[dict[str, Any]]:
    """Plain string, or OpenAI-style multimodal content list."""
    t = (text or "").strip() or "（master 发来一张图，请 Lucy 用自己的方式回应）"
    if not image_path:
        return t
    url = encode_image_data_url(image_path, max_edge=max_edge)
    return [
        {"type": "text", "text": t},
        {"type": "image_url", "image_url": {"url": url}},
    ]


def content_has_image(content: Any) -> bool:
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image_url":
                return True
    return False
