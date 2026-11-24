# -*- coding: utf-8 -*-
"""Locked Lucy post: soft demuffle + SR-less mid_balance toward a reference wav."""
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
import torch
import torchaudio

SOFT_AMOUNT = 0.05


def load_mono(path, sr_target=None):
    x, sr = sf.read(str(path), always_2d=False)
    x = np.asarray(x, dtype=np.float32)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if sr_target and sr != sr_target:
        x = (
            torchaudio.functional.resample(
                torch.from_numpy(x).unsqueeze(0), sr, sr_target
            )
            .squeeze(0)
            .numpy()
        )
        sr = sr_target
    return x, sr


def soft_de_muffle(x, amount=SOFT_AMOUNT):
    d = np.empty_like(x)
    d[0] = x[0]
    d[1:] = x[1:] - 0.97 * x[:-1]
    y = (1.0 - amount) * x + amount * d
    peak = np.max(np.abs(y)) + 1e-8
    if peak > 0.98:
        y *= 0.98 / peak
    return y


def mild_air(x, amount=0.08):
    d = np.empty_like(x)
    d[0] = x[0]
    d[1:] = x[1:] - 0.95 * x[:-1]
    y = (1.0 - amount) * x + amount * d
    peak = np.max(np.abs(y)) + 1e-8
    if peak > 0.98:
        y *= 0.98 / peak
    return y


def _mean_env(x, n_fft=2048, hop=512):
    w = np.hanning(n_fft).astype(np.float32)
    acc = None
    n = 0
    for i in range(0, max(1, len(x) - n_fft + 1), hop):
        mag = np.abs(np.fft.rfft(x[i : i + n_fft] * w)) + 1e-10
        acc = mag if acc is None else acc + mag
        n += 1
    return acc / max(n, 1)


def _smooth_log(v, k=41):
    k = max(3, k | 1)
    ker = np.hanning(k)
    ker /= ker.sum()
    pad = k // 2
    return np.convolve(np.pad(v, (pad, pad), mode="edge"), ker, mode="valid")


def mid_balance(gen, orig, sr, n_fft=2048, hop=512):
    w = np.hanning(n_fft).astype(np.float32)
    n = min(len(gen), len(orig))
    g = _smooth_log(np.log(_mean_env(gen[:n], n_fft, hop)))
    o = _smooth_log(np.log(_mean_env(orig[:n], n_fft, hop)))
    m = min(len(g), len(o), n_fft // 2 + 1)
    freqs = np.linspace(0, sr / 2, m)
    strength = np.zeros(m, dtype=np.float32)
    bias_db = np.zeros(m, dtype=np.float32)
    for i, f in enumerate(freqs):
        if f < 500:
            strength[i] = 0.90
            bias_db[i] = 1.0 if f < 400 else 0.5
        elif f < 2000:
            strength[i] = 0.95
            if 700 <= f <= 1800:
                bias_db[i] = -1.5
            elif 1800 < f <= 2200:
                bias_db[i] = -0.6
        elif f < 4000:
            strength[i] = 0.55
        elif f < 8000:
            strength[i] = 0.25
        else:
            strength[i] = 0.12
    gain = np.clip(
        np.exp((o[:m] - g[:m]) * strength) * (10.0 ** (bias_db / 20.0)), 0.55, 2.2
    )
    for i, f in enumerate(freqs):
        if f >= 8000:
            gain[i] = min(gain[i], 1.15)
        if 500 <= f <= 2000:
            gain[i] = min(gain[i], 1.05)
    out = np.zeros(len(gen) + n_fft, dtype=np.float32)
    norm = np.zeros_like(out)
    for i in range(0, len(gen) - n_fft + 1, hop):
        frame = gen[i : i + n_fft] * w
        spec = np.fft.rfft(frame)
        g2 = np.ones_like(spec, dtype=np.float32)
        g2[:m] = gain
        frame2 = np.fft.irfft(spec * g2, n=n_fft).real.astype(np.float32)
        out[i : i + n_fft] += frame2 * w
        norm[i : i + n_fft] += w * w
    y = out[: len(gen)] / (norm[: len(gen)] + 1e-8)
    peak = np.max(np.abs(y)) + 1e-8
    if peak > 0.98:
        y *= 0.98 / peak
    return y


def rms(x):
    return float(np.sqrt(np.mean(x * x) + 1e-12))


def apply_locked_post(audio, sr, ref_wav: Optional[Path] = None):
    y = soft_de_muffle(audio, SOFT_AMOUNT)
    y = mild_air(y, 0.08)
    if ref_wav is not None and Path(ref_wav).exists():
        orig, _ = load_mono(ref_wav, sr)
        y = mid_balance(y, orig, sr)
        y = np.clip(y * (rms(orig) / (rms(y) + 1e-12)), -1, 1)
    return y
