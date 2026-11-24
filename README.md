# LucyValentine-PIM-001

Private desktop companion inspired by **Lucy ~The Eternity She Wished For~**:  
**Chinese in → Japanese line + Chinese gloss → face + optional local TTS**.

> Unofficial fan project — not affiliated with the game’s rights holders.  
> Code is MIT. Sprites / game audio / trained weights are **bring your own** — see [NOTICE](NOTICE).

## One-click setup

From the repo root (Windows):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_lucy.ps1
# set your cloud key (example):
$env:QIANWEN_API_KEY = "sk-..."
python scripts\run_desktop_lucy.py
```

The setup script will:

- create `output/`, `sessions/`, `images_hq/`, `voice_models/`
- copy `settings.example.yaml` → `settings.yaml` if missing
- point `project_root` / TTS worker paths at this repo
- `pip install -r companion/requirements.txt`
- check that inference weights exist (does **not** train anything)

## Voice (inference only)

Only **ready weights + load**. No training instructions in this repo.

Put checkpoints as described in [`voice_models/README.md`](voice_models/README.md), then enable voice in `settings.yaml`.

## LLM

Prefer env vars for keys (`llm.api_key_env`). Never commit `settings.yaml`.

| Mode | Hint |
|------|------|
| Ollama | `base_url: http://127.0.0.1:11434/v1`, `api_key: ollama` |
| Cloud | set `$env:QIANWEN_API_KEY` (or your provider) |

## Layout

| Path | Role |
|------|------|
| `companion/` | Agent, desktop pet, configs |
| `scripts/setup_lucy.ps1` | One-click path init |
| `scripts/companion_tts_worker.py` | GPT-SoVITS inference worker |
| `voice_models/` | Where to drop inference weights (docs only) |

Heavy trees (`GPT-SoVITS-*`, `RVC`, `images_hq`, `voice`, `dataset`, `output`) stay **out of git**.

## Desktop pet

Right-click: chat history (▶ if wav saved), info, settings, quit.  
Settings → 声音 → 播放方式: **整句** (default) or **一句一句**.

## Before you publish

1. **Rotate** any API key that ever appeared in a file or chat.
2. Confirm `.gitignore` excludes secrets, assets, and IDE junk.
3. Git commits must use **your** `user.name` / `user.email` — **not** a Cursor-provided address.

```powershell
git config user.name  "Your Name"
git config user.email "you@example.com"
```

## License

MIT — [LICENSE](LICENSE), [NOTICE](NOTICE), [SECURITY](SECURITY.md).
