# -*- coding: utf-8 -*-
"""Ornstein-Uhlenbeck mean-reverting process for long-term affective drift."""
from __future__ import annotations

import math
import random


def ou_step(
    x: float,
    mu: float,
    dt_hours: float,
    theta: float = 0.35,
    sigma: float = 0.04,
    rng: random.Random | None = None,
) -> float:
    """
    dX = theta*(mu-X)dt + sigma*dW
    dt is in hours; theta is calibrated roughly per day-ish scale.
    """
    rng = rng or random
    dt = max(0.0, float(dt_hours)) / 24.0  # convert to days
    if dt <= 0:
        return x
    # exact OU discretization
    decay = math.exp(-theta * dt)
    noise_scale = sigma * math.sqrt(max(1e-9, (1.0 - decay * decay) / (2.0 * theta)))
    return mu + (x - mu) * decay + noise_scale * rng.gauss(0.0, 1.0)


def ou_vector(
    values: dict[str, float],
    baselines: dict[str, float],
    dt_hours: float,
    theta: float = 0.35,
    sigma: float = 0.04,
    rng: random.Random | None = None,
) -> dict[str, float]:
    out = {}
    for k, x in values.items():
        mu = float(baselines.get(k, x))
        out[k] = ou_step(float(x), mu, dt_hours, theta=theta, sigma=sigma, rng=rng)
    return out
