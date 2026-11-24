# -*- coding: utf-8 -*-
"""Local Lucy 'battery' — hardcoded 100° ↔ 100M tokens; empty → full refill."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CAPACITY = 100.0
DEFAULT_TOKENS_PER_FULL = 1_000_000  # 1M tokens = 100° (free-tier scale)


@dataclass
class PowerSnapshot:
    charge: float
    capacity: float
    pct: float
    tokens_lifetime: int
    tokens_this_cycle: int
    tokens_per_full: int
    cycle: int
    just_recovered: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "charge": round(self.charge, 3),
            "capacity": self.capacity,
            "pct": round(self.pct, 2),
            "tokens_lifetime": self.tokens_lifetime,
            "tokens_this_cycle": self.tokens_this_cycle,
            "tokens_per_full": self.tokens_per_full,
            "cycle": self.cycle,
            "just_recovered": self.just_recovered,
        }


class PowerMeter:
    """Persist token drain as degrees of power. When empty, refill to full."""

    def __init__(
        self,
        path: Path,
        *,
        capacity: float = DEFAULT_CAPACITY,
        tokens_per_full: int = DEFAULT_TOKENS_PER_FULL,
        enabled: bool = True,
    ):
        self.path = Path(path)
        self.enabled = bool(enabled)
        self.capacity = float(capacity) if capacity > 0 else DEFAULT_CAPACITY
        self.tokens_per_full = (
            int(tokens_per_full) if tokens_per_full > 0 else DEFAULT_TOKENS_PER_FULL
        )
        self.charge = self.capacity
        self.tokens_lifetime = 0
        self.tokens_this_cycle = 0
        self.cycle = 1
        self.updated_at = time.time()
        self._just_recovered = False
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._save()
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        self.capacity = float(data.get("capacity") or self.capacity)
        # Prefer settings constructor value when file still has a stale scale
        file_tpf = int(data.get("tokens_per_full") or 0)
        if file_tpf > 0:
            self.tokens_per_full = file_tpf
        self.charge = float(data.get("charge", self.capacity))
        self.tokens_lifetime = int(data.get("tokens_lifetime") or 0)
        self.tokens_this_cycle = int(data.get("tokens_this_cycle") or 0)
        self.cycle = int(data.get("cycle") or 1)
        self.updated_at = float(data.get("updated_at") or time.time())
        self.charge = max(0.0, min(self.capacity, self.charge))

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "charge": round(self.charge, 4),
            "capacity": self.capacity,
            "tokens_per_full": self.tokens_per_full,
            "tokens_lifetime": self.tokens_lifetime,
            "tokens_this_cycle": self.tokens_this_cycle,
            "cycle": self.cycle,
            "updated_at": self.updated_at,
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def snapshot(self, *, consume_flags: bool = True) -> PowerSnapshot:
        pct = 0.0 if self.capacity <= 0 else 100.0 * self.charge / self.capacity
        snap = PowerSnapshot(
            charge=self.charge,
            capacity=self.capacity,
            pct=max(0.0, min(100.0, pct)),
            tokens_lifetime=self.tokens_lifetime,
            tokens_this_cycle=self.tokens_this_cycle,
            tokens_per_full=self.tokens_per_full,
            cycle=self.cycle,
            just_recovered=self._just_recovered,
        )
        if consume_flags:
            self._just_recovered = False
        return snap

    def record_tokens(self, tokens: int) -> PowerSnapshot:
        """Consume power from LLM usage; refill when drained."""
        if not self.enabled:
            return self.snapshot(consume_flags=False)
        n = max(0, int(tokens or 0))
        if n <= 0:
            return self.snapshot(consume_flags=False)
        self.tokens_lifetime += n
        self.tokens_this_cycle += n
        drain = self.capacity * (n / float(self.tokens_per_full))
        self.charge = max(0.0, self.charge - drain)
        if self.charge <= 1e-9:
            self.charge = self.capacity
            self.tokens_this_cycle = 0
            self.cycle += 1
            self._just_recovered = True
        self.updated_at = time.time()
        self._save()
        return self.snapshot(consume_flags=False)
