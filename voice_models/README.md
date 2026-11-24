# Voice models (inference only)

This folder is for **ready-to-run** Lucy TTS weights.  
There is **no training guide** in this repo — train elsewhere if you need new weights.

## Place these files

Copy into your GPT-SoVITS install (default layout under repo root):

```text
GPT-SoVITS-v3lora-20250401/
  GPT_weights_v3/
    lucy-e10.ckpt          # or lucy-e5.ckpt
  SoVITS_weights_v3/
    lucy_e2_s1904_l32.pth  # matching SoVITS / LoRA checkpoint
  logs/lucy/5-wav32k/
    Voices-lucy0054_jp.wav # short JP reference clip used by the worker
  TEMP/
    tts_lucy.yaml          # points at the two weight paths above
```

You may instead put the two weight files here and point `TEMP/tts_lucy.yaml` at them.

## Load

1. Run `scripts/setup_lucy.ps1` once (creates `settings.yaml` + path checks).
2. Set `voice.enabled: true` and a valid `voice.python_exe` to the GPT-SoVITS runtime.
3. Start the desktop pet — the worker loads weights automatically; no training step.

Weights, game audio, and sprites are **not** redistributed by this project (see root `NOTICE`).
