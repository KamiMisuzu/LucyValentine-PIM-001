# -*- coding: utf-8 -*-
"""Persistent TTS worker for Lucy companion (locked tts_balanced).

Protocol (stdin / stdout). Every protocol line is prefixed with LUCY_TTS:
  LUCY_TTS:{"cmd":"synth","text":"...","out":"..."}
  -> LUCY_TTS:{"ok":true,"path":"...","tts_text":"マスター..."}
GSV logs go to output/companion_voice/tts_worker.log (not stdout).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

# Repo root: LUCY_ROOT env, else parent of scripts/
ROOT = Path(os.environ.get("LUCY_ROOT", "")).expanduser() if os.environ.get("LUCY_ROOT") else Path(
    __file__
).resolve().parents[1]
GSV = ROOT / "GPT-SoVITS-v3lora-20250401"
OUT = ROOT / "output" / "companion_voice"
OUT.mkdir(parents=True, exist_ok=True)
LOG_PATH = OUT / "tts_worker.log"

os.chdir(GSV)
sys.path.insert(0, str(GSV))
sys.path.insert(0, str(GSV / "GPT_SoVITS"))
sys.path.insert(0, str(ROOT / "scripts"))

_PROTO = "LUCY_TTS:"
_real_out = sys.stdout
_log = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
sys.stderr = _log


def emit(obj: dict) -> None:
    _real_out.write(_PROTO + json.dumps(obj, ensure_ascii=False) + "\n")
    _real_out.flush()


def log(msg: str) -> None:
    _log.write(msg.rstrip() + "\n")
    _log.flush()


import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
import torch  # noqa: E402
import torchaudio  # noqa: E402
from lucy_post import apply_locked_post, soft_de_muffle  # noqa: E402

STYLE = json.loads((ROOT / "dataset/infer_style_soul.json").read_text(encoding="utf-8"))
META = json.loads(
    (ROOT / "dataset/compare_neutral_meta.json").read_text(encoding="utf-8")
)
# TTS prompt: short 3–10s line that already says マスター (0040_1 is too short for GSV)
REF_WAV = GSV / "logs" / "lucy" / "5-wav32k" / "Voices-lucy0054_jp.wav"
PROMPT = "マスター、そんな嘘は通じません。"
# Spectral mid_balance target stays the locked neutral original
BALANCE_REF = Path(META["wav"])
SOFT = float(STYLE.get("soft_amount", 0.05))
SR_BLEND = float(STYLE.get("sr_blend", 0.40))
# Post FX stays locked (soft+SR+mid_balance). Decode tighter than soul open sampling.
DEC = {
    "top_k": 4,
    "top_p": 0.8,
    "temperature": 0.6,
    "repetition_penalty": 1.5,
    "sample_steps": 32,
    "speed_factor": 1.1,
}

# Light emotion coloring on locked decode (keeps post-FX / ref wav fixed)
EMO_DEC = {
    "neutral": {},
    "happy": {"speed_factor": 1.14, "temperature": 0.62},
    "joyful": {"speed_factor": 1.16, "temperature": 0.64},
    "affection": {"speed_factor": 1.05, "temperature": 0.58},
    "shy": {"speed_factor": 1.02, "temperature": 0.55},
    "serious": {"speed_factor": 1.08, "temperature": 0.55},
    "worried": {"speed_factor": 1.02, "temperature": 0.58},
    "anxious": {"speed_factor": 1.04, "temperature": 0.66},
    "pleading": {"speed_factor": 0.98, "temperature": 0.60},
    "sad": {"speed_factor": 0.96, "temperature": 0.55},
    "angry": {"speed_factor": 1.12, "temperature": 0.68},
    "surprised": {"speed_factor": 1.15, "temperature": 0.65},
}

_tts = None


def _dec_for(emotion: str) -> dict:
    base = dict(DEC)
    base.update(EMO_DEC.get((emotion or "neutral").lower(), {}))
    return base


def _break_long_ja(text: str, max_len: int = 20) -> str:
    """Promote 、 breaks to 。 — long clauses get T2S early-EOS (尾半句不说)."""
    chunks = re.split(r"(?<=[。！？])", text)
    out: list[str] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        if len(chunk) <= max_len:
            if chunk[-1] not in "。！？":
                chunk += "。"
            out.append(chunk)
            continue
        bits = chunk.split("、")
        buf = ""
        for i, bit in enumerate(bits):
            piece = bit if i == len(bits) - 1 else bit + "、"
            if buf and len(buf) + len(piece) > max_len:
                if buf.endswith("、"):
                    buf = buf[:-1] + "。"
                elif buf[-1] not in "。！？":
                    buf += "。"
                out.append(buf)
                buf = piece
            else:
                buf += piece
        if buf:
            if buf.endswith("、"):
                buf = buf[:-1] + "。"
            elif buf[-1] not in "。！？":
                buf += "。"
            out.append(buf)
    return "".join(out)


def _tts_units(spoken: str, pack_max: int = 36) -> list[str]:
    """Sentence units for cut0. Pack short neighbors to cut inference count.

    Quality lock: still one short clause-group per T2S (avoids long-clause early-EOS);
    packing only joins already-safe 。/！/？ fragments up to pack_max chars.
    """
    units = [u.strip() for u in re.split(r"(?<=[。！？])", spoken) if u and u.strip()]
    if not units:
        return [spoken] if spoken else []
    # First: glue tiny fragments (「ルーシーは。」) into the next clause
    merged: list[str] = []
    i = 0
    while i < len(units):
        cur = units[i]
        if len(cur) < 10 and i + 1 < len(units):
            nxt = units[i + 1]
            if cur.endswith(("。", "！", "？")):
                cur = cur[:-1] + "、" + nxt
            else:
                cur = cur + nxt
            i += 2
            merged.append(cur)
        else:
            merged.append(cur)
            i += 1
    # Second: pack consecutive safe units under pack_max (fewer dual-grade CFM runs)
    packed: list[str] = []
    buf = ""
    for u in merged:
        if not buf:
            buf = u
        elif len(buf) + len(u) <= pack_max:
            buf = buf + u
        else:
            packed.append(buf)
            buf = u
    if buf:
        packed.append(buf)
    return packed


def ja_tts_text(text: str) -> str:
    """Force loanword readings to match original JP VA (マスター / ルーシー).

    Also scrub Latin units/digits that make T2S runaway to 1500 tokens
    (quality lock unchanged — same weights / dual-pass; only safer input text).
    """
    # Drop unpaired UTF-16 surrogates (breaks utf-8 encode inside GSV)
    t = "".join(ch for ch in (text or "") if not (0xD800 <= ord(ch) <= 0xDFFF))
    t = t.strip()
    # Do NOT use \b after the word: JP particles (は/の/が…) are word-chars in Unicode,
    # so "masterは" would fail to match. Block only Latin letters on either side.
    t = re.sub(r"(?i)(?<![A-Za-z])master(?![A-Za-z])", "マスター", t)
    t = re.sub(r"(?i)(?<![A-Za-z])lucy(?![A-Za-z])", "ルーシー", t)
    t = t.replace("ﾏｽﾀｰ", "マスター").replace("ﾙｰｼｰ", "ルーシー")
    t = t.replace("がいそば", "がそば")
    # Ellipsis → sentence break (helps cut3); avoid マスター、、 double pauses
    t = t.replace("……", "。").replace("...", "。").replace("…", "、")
    t = re.sub(r"[、]{2,}", "、", t)
    t = re.sub(r"[。]{2,}", "。", t)
    # ASCII science units → kana (prevents "6.seven kilometersh" style explosions)
    t = re.sub(r"(?i)\s*km/h\b", "キロ", t)
    t = re.sub(r"(?i)\s*m/s\b", "メートル毎秒", t)
    t = re.sub(r"(?i)\s*°\s*C\b", "度", t)
    t = re.sub(r"(?i)\s*℃", "度", t)
    t = re.sub(r"(?i)\s*mm\b", "ミリ", t)
    t = re.sub(r"(?i)\s*%", "パーセント", t)
    t = t.replace("南宁", "ナンニン")
    return _break_long_ja(t)


def _get_tts():
    global _tts
    if _tts is None:
        # silence library prints on stdout during load
        old = sys.stdout
        sys.stdout = _log
        try:
            from GPT_SoVITS.TTS_infer_pack.TTS import TTS, TTS_Config

            cfg = TTS_Config(str(GSV / "TEMP" / "tts_lucy.yaml"))
            _tts = TTS(cfg)
        finally:
            sys.stdout = old
    return _tts


def _run_once(
    tts,
    text: str,
    super_sampling: bool,
    emotion: str = "neutral",
    *,
    split_method: str = "cut0",
):
    dec = _dec_for(emotion)
    inputs = {
        "text": text,
        "text_lang": "ja",
        "ref_audio_path": str(REF_WAV),
        "prompt_text": PROMPT,
        "prompt_lang": "ja",
        "top_k": int(dec["top_k"]),
        "top_p": float(dec["top_p"]),
        "temperature": float(dec["temperature"]),
        # Per-unit cut0: one short clause per T2S — avoids mid-sentence early EOS
        "text_split_method": split_method,
        "batch_size": 1,
        "speed_factor": float(dec["speed_factor"]),
        "seed": 42,
        "parallel_infer": True,
        "repetition_penalty": float(dec["repetition_penalty"]),
        "sample_steps": int(dec["sample_steps"]),
        "super_sampling": super_sampling,
    }
    chunks = []
    sr = None
    old = sys.stdout
    sys.stdout = _log
    try:
        for item in tts.run(inputs):
            if isinstance(item, tuple) and len(item) == 2:
                sr, audio = item
                chunks.append(np.asarray(audio, dtype=np.float32))
    finally:
        sys.stdout = old
    if not chunks:
        return 48000, np.zeros(1, dtype=np.float32)
    audio = np.concatenate(chunks)
    peak = np.max(np.abs(audio)) + 1e-8
    if peak > 1.0:
        audio /= peak
    return sr, audio


def _blend_dual(nat48: np.ndarray, sr_audio: np.ndarray) -> np.ndarray:
    n = min(len(nat48), len(sr_audio))
    mixed = (1.0 - SR_BLEND) * nat48[:n] + SR_BLEND * sr_audio[:n]
    if len(nat48) > n:
        mixed = np.concatenate([mixed, nat48[n:]])
    elif len(sr_audio) > n:
        mixed = np.concatenate([mixed, sr_audio[n:]])
    peak = np.max(np.abs(mixed)) + 1e-8
    if peak > 0.98:
        mixed *= 0.98 / peak
    return mixed


def _audio_to_unit_float(audio: np.ndarray) -> np.ndarray:
    """GSV yields int16-scaled arrays; normalize to ~[-1, 1] float."""
    x = np.asarray(audio, dtype=np.float32)
    peak = float(np.max(np.abs(x))) + 1e-8
    if peak > 2.0:  # int16 range
        x = x / 32768.0
    peak = float(np.max(np.abs(x))) + 1e-8
    if peak > 1.0:
        x = x / peak
    return x


def _apply_ap_bwe(tts, wav: np.ndarray, sr: int) -> tuple[np.ndarray, int]:
    """Same AP-BWE path as TTS.audio_postprocess(super_sampling=True). ~0.02s."""
    tts.init_sr_model()
    if getattr(tts, "sr_model_not_exist", True) or tts.sr_model is None:
        up = (
            torchaudio.functional.resample(
                torch.from_numpy(wav).unsqueeze(0), sr, 48000
            )
            .squeeze(0)
            .numpy()
        )
        return up.astype(np.float32), 48000
    # GSV keeps AP-BWE on CUDA — input must match (was CPU → hard fail, no wav)
    device = getattr(tts.sr_model, "device", None)
    if device is None:
        try:
            device = next(tts.sr_model.model.parameters()).device
        except Exception:
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    audio_t = (
        torch.from_numpy(np.asarray(wav, dtype=np.float32))
        .unsqueeze(0)
        .to(device=device, dtype=torch.float32)
    )
    with torch.inference_mode():
        out, out_sr = tts.sr_model(audio_t, int(sr))
    out = np.asarray(out, dtype=np.float32)
    peak = float(np.max(np.abs(out))) + 1e-8
    if peak > 1.0:
        out = out / peak
    return out, int(out_sr)


def _balanced_from_natural(tts, natural: np.ndarray, sr_nat: int) -> tuple[np.ndarray, int]:
    """One CFM decode → soft natural@48k + AP-BWE → same mid blend as dual-pass.

    Seed is fixed (42), so a second full T2S+CFM with super_sampling=True was
    regenerating the same waveform then spending ~20ms on AP-BWE — pure waste.
    """
    wav = _audio_to_unit_float(natural)
    sr48 = 48000
    nat48 = (
        torchaudio.functional.resample(
            torch.from_numpy(wav).unsqueeze(0), int(sr_nat), sr48
        )
        .squeeze(0)
        .numpy()
    )
    nat48 = soft_de_muffle(nat48.astype(np.float32), SOFT)
    try:
        sr_audio, sr_out = _apply_ap_bwe(tts, wav, int(sr_nat))
    except Exception as exc:
        log(f"AP-BWE failed ({exc}); fallback resample blend")
        sr_audio = nat48.copy()
        sr_out = sr48
    if len(sr_audio) == 0:
        return nat48, sr48
    if int(sr_out) != sr48:
        sr_audio = (
            torchaudio.functional.resample(
                torch.from_numpy(sr_audio).unsqueeze(0), int(sr_out), sr48
            )
            .squeeze(0)
            .numpy()
        )
    return _blend_dual(nat48, sr_audio.astype(np.float32)), sr48


def _synth_units(
    text: str, emotion: str = "neutral"
):
    """Yield (index, total, unit_text, audio, sr, spoken_full) per clause."""
    spoken = ja_tts_text(text)
    units = _tts_units(spoken)
    log(f"TTS units ({len(units)}): " + " | ".join(repr(u) for u in units))
    tts = _get_tts()
    _empty = tts.empty_cache
    tts.empty_cache = lambda: None  # type: ignore[method-assign]
    sr48 = 48000
    try:
        n = len(units)
        for i, unit in enumerate(units):
            t_u = time.time()
            sr_nat, natural = _run_once(
                tts, unit, False, emotion=emotion, split_method="cut0"
            )
            mixed_u, sr48 = _balanced_from_natural(tts, natural, int(sr_nat))
            unit_sec = float(len(mixed_u)) / float(sr48)
            expect_u = max(0.8, 0.055 * len(unit))
            log(
                f"  unit[{i}] chars={len(unit)} sec={unit_sec:.2f} "
                f"infer={time.time() - t_u:.2f}s expect>~{expect_u:.1f} text={unit!r}"
            )
            if unit_sec < expect_u * 0.5:
                log(f"  WARN unit[{i}] still short after clause split")
            yield i, n, unit, mixed_u, sr48, spoken
    finally:
        tts.empty_cache = _empty  # type: ignore[method-assign]
        try:
            _empty()
        except Exception:
            pass


def synth_balanced(text: str, emotion: str = "neutral") -> tuple[np.ndarray, int, str]:
    parts: list[np.ndarray] = []
    sr48 = 48000
    spoken = ""
    gap = np.zeros(int(0.12 * 48000), dtype=np.float32)
    for i, total, unit, mixed_u, sr48, spoken in _synth_units(text, emotion):
        parts.append(mixed_u)
        if i + 1 < total:
            parts.append(gap)

    mixed = np.concatenate(parts) if parts else np.zeros(1, dtype=np.float32)
    sec = float(len(mixed)) / float(sr48)
    expect = max(2.0, 0.055 * len(spoken))
    if sec < expect * 0.45:
        log(
            f"WARN short TTS: {sec:.2f}s for {len(spoken)} chars "
            f"(expect>~{expect:.1f}s); spoken={spoken!r}"
        )
    bal = apply_locked_post(
        mixed, sr48, BALANCE_REF if BALANCE_REF.exists() else None
    )
    return bal, sr48, spoken


def _out_path_from_req(req: dict, emotion: str) -> Path:
    out = req.get("out")
    if out:
        out_path = Path(out)
    else:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        out_path = OUT / f"lucy_{stamp}_{emotion}.wav"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return out_path


def handle_stream(req: dict) -> None:
    """Emit one partial per unit, then a final done message with full wav."""
    text = str(req.get("text", "")).strip()
    if not text:
        emit({"ok": False, "error": "empty text"})
        return
    emotion = str(req.get("emotion", "neutral")).replace("/", "_") or "neutral"
    out_path = _out_path_from_req(req, emotion)
    t0 = time.time()
    parts: list[np.ndarray] = []
    part_paths: list[str] = []
    sr48 = 48000
    spoken = ""
    gap = np.zeros(int(0.12 * 48000), dtype=np.float32)
    try:
        for i, total, unit, mixed_u, sr48, spoken in _synth_units(text, emotion):
            unit_audio = apply_locked_post(
                mixed_u, sr48, BALANCE_REF if BALANCE_REF.exists() else None
            )
            unit_path = out_path.with_name(f"{out_path.stem}_u{i}{out_path.suffix}")
            sf.write(str(unit_path), unit_audio, sr48)
            part_paths.append(str(unit_path))
            parts.append(mixed_u)
            if i + 1 < total:
                parts.append(gap)
            emit(
                {
                    "ok": True,
                    "partial": True,
                    "index": i,
                    "total": total,
                    "path": str(unit_path),
                    "unit_text": unit,
                    "tts_text": spoken,
                    "emotion": emotion,
                    "style": "tts_balanced",
                }
            )
        mixed = np.concatenate(parts) if parts else np.zeros(1, dtype=np.float32)
        bal = apply_locked_post(
            mixed, sr48, BALANCE_REF if BALANCE_REF.exists() else None
        )
        sf.write(str(out_path), bal, sr48)
        emit(
            {
                "ok": True,
                "done": True,
                "path": str(out_path),
                "parts": part_paths,
                "sr": sr48,
                "seconds": round(len(bal) / float(sr48), 3),
                "elapsed": round(time.time() - t0, 2),
                "style": "tts_balanced",
                "emotion": emotion,
                "tts_text": spoken,
            }
        )
    except Exception as e:
        log(f"stream error: {e}")
        emit({"ok": False, "error": str(e)})


def handle(req: dict) -> dict | None:
    cmd = str(req.get("cmd", "synth"))
    if cmd == "ping":
        return {"ok": True, "pong": True}
    if cmd == "quit":
        return {"ok": True, "bye": True}
    if cmd == "synth_stream":
        handle_stream(req)
        return None
    text = str(req.get("text", "")).strip()
    if not text:
        return {"ok": False, "error": "empty text"}
    emotion = str(req.get("emotion", "neutral")).replace("/", "_") or "neutral"
    out_path = _out_path_from_req(req, emotion)
    t0 = time.time()
    audio, sr, spoken = synth_balanced(text, emotion=emotion)
    sf.write(str(out_path), audio, sr)
    return {
        "ok": True,
        "path": str(out_path),
        "sr": sr,
        "seconds": round(len(audio) / float(sr), 3),
        "elapsed": round(time.time() - t0, 2),
        "style": "tts_balanced",
        "emotion": emotion,
        "tts_text": spoken,
    }


def main():
    emit({"ok": True, "ready": False, "msg": "loading"})
    try:
        _get_tts()
        emit({"ok": True, "ready": True, "style": "tts_balanced"})
    except Exception as e:
        emit({"ok": False, "ready": False, "error": str(e)})
        return 1

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if line.startswith(_PROTO):
            line = line[len(_PROTO) :]
        try:
            req = json.loads(line)
            resp = handle(req)
            if resp is not None:
                emit(resp)
            if req.get("cmd") == "quit":
                return 0
        except Exception as e:
            log(f"handle error: {e}")
            emit({"ok": False, "error": str(e)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
