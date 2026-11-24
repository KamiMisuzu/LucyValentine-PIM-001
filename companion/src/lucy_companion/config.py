# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def discover_project_root() -> Path:
    """Repo root: …/Lucy when this file lives at companion/src/lucy_companion/config.py."""
    env = os.environ.get("LUCY_ROOT", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve()
    # lucy_companion → src → companion → <root>
    cand = here.parents[3]
    if (cand / "companion" / "src").is_dir():
        return cand
    return here.parents[2]


DEFAULT_ROOT = discover_project_root()


def _as_path(root: Path, value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (root / p)


@dataclass
class Settings:
    project_root: Path
    raw: dict[str, Any] = field(default_factory=dict)
    config_path: Path | None = None

    @property
    def llm(self) -> dict[str, Any]:
        return self.raw.get("llm", {})

    @property
    def paths(self) -> dict[str, Any]:
        return self.raw.get("paths", {})

    @property
    def memory(self) -> dict[str, Any]:
        return self.raw.get("memory", {})

    @property
    def face(self) -> dict[str, Any]:
        return self.raw.get("face", {})

    @property
    def voice(self) -> dict[str, Any]:
        return self.raw.get("voice", {})

    @property
    def chat(self) -> dict[str, Any]:
        return self.raw.get("chat", {})

    @property
    def desktop(self) -> dict[str, Any]:
        return self.raw.get("desktop", {})

    @property
    def power(self) -> dict[str, Any]:
        return self.raw.get("power", {})

    def path(self, key: str) -> Path:
        return _as_path(self.project_root, self.paths[key])

    def api_key(self) -> str:
        env_name = self.llm.get("api_key_env", "DEEPSEEK_API_KEY")
        key = os.environ.get(env_name, "")
        if not key:
            # allow inline for local private use only — never commit real keys
            key = str(self.llm.get("api_key", "") or "")
        if not key:
            base = str(self.llm.get("base_url", ""))
            # Ollama OpenAI-compatible server accepts any non-empty key
            if "11434" in base or "ollama" in base.lower():
                return "ollama"
            raise RuntimeError(
                f"Missing API key. Set env {env_name} or llm.api_key in settings.yaml"
            )
        return key


def load_settings(path: str | Path | None = None) -> Settings:
    root = discover_project_root()
    if path:
        cfg_path = Path(path)
    else:
        cfg_path = root / "companion" / "config" / "settings.yaml"
    if not cfg_path.exists():
        example = root / "companion" / "config" / "settings.example.yaml"
        if not example.exists():
            raise FileNotFoundError(f"Missing settings: {cfg_path}")
        cfg_path = example

    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    # Prefer layout next to config file; allow override via project_root
    inferred = cfg_path.resolve().parent.parent.parent
    pr = raw.get("project_root")
    if not pr or str(pr).strip() in {".", ""}:
        project_root = inferred if (inferred / "companion").is_dir() else root
    else:
        project_root = Path(str(pr)).expanduser()
        if not project_root.is_absolute():
            project_root = (inferred / project_root).resolve()
    return Settings(project_root=project_root, raw=raw, config_path=cfg_path)


def _deep_set(raw: dict[str, Any], dotted: str, value: Any) -> None:
    """Set nested key like 'llm.model' on a dict, creating dict parents."""
    parts = [p for p in dotted.split(".") if p]
    if not parts:
        return
    cur: dict[str, Any] = raw
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value


def apply_settings_patch(settings: Settings, patch: dict[str, Any]) -> Path:
    """Merge flat dotted keys into settings.raw and write settings.yaml.

    Note: PyYAML rewrite drops comments in the file.
    """
    for key, value in patch.items():
        if key == "project_root":
            settings.raw["project_root"] = value
            settings.project_root = Path(str(value))
        else:
            _deep_set(settings.raw, str(key), value)

    cfg_path = settings.config_path
    if cfg_path is None:
        cfg_path = settings.project_root / "companion" / "config" / "settings.yaml"
        settings.config_path = cfg_path
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        settings.raw,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    cfg_path.write_text(text, encoding="utf-8")
    return cfg_path
