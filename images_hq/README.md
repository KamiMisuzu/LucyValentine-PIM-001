# Sprites (`images_hq`) — bring your own

This folder holds **upscaled RGBA standees** the desktop pet loads as faces.  
PNG payloads are **not** shipped in git (see root `NOTICE`). You build them locally.

## What the pet expects

- Directory: `images_hq/` (or override `paths.images_dir` in `settings.yaml`)
- Files: `Images-lNNN.png` (e.g. `Images-l001.png`), RGBA, character on transparent bg
- Source naming must match what the companion emotion/face mapper already uses

## How to obtain materials (legal BYO)

1. **Own a legal copy** of *Lucy ~The Eternity She Wished For~* (or other art you have rights to use).
2. Export / copy the character standee PNGs you are allowed to use into a sibling folder:

```text
<repo>/
  images/           ← your original standees (Images-l*.png)
  images_hq/        ← output of the upscale step (this folder)
```

3. Do **not** redistribute game sprites or upscales unless you have permission. This project only ships the upscale **tooling**.

## Upscale (Real-ESRGAN, RGBA-safe)

The repo script crops to the alpha bbox, upscales RGB with Real-ESRGAN ncnn-vulkan (`realesrgan-x4plus-anime` ×4 by default), then merges a Lanczos-scaled alpha — avoids full-frame seams and keeps transparency.

### 1. Install Real-ESRGAN ncnn-vulkan

Download a Windows release from [xinntao/Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN/releases) (ncnn-vulkan build) and unpack so this exists:

```text
<repo>/tools/realesrgan-ncnn-vulkan/realesrgan-ncnn-vulkan.exe
```

(models next to the exe, as in the upstream zip)

### 2. Dependencies

```powershell
pip install pillow
```

Use any Python 3.10+ on `PATH`, or the GPT-SoVITS runtime python if you already have it.

### 3. Run

From the repo root:

```powershell
# optional: set root explicitly
$env:LUCY_ROOT = (Get-Location).Path

# single GPU example
powershell -ExecutionPolicy Bypass -File scripts\upscale_lucy_sprites.ps1 -Gpus "0"

# resume without redoing finished files
powershell -ExecutionPolicy Bypass -File scripts\upscale_lucy_sprites.ps1 -Gpus "0" -SkipExisting
```

Or call Python directly:

```powershell
python scripts\upscale_lucy_sprites_rgba.py --scale 4 --model realesrgan-x4plus-anime --gpus 0
```

### 4. Point the companion at the result

`setup_lucy.ps1` already defaults `paths.images_dir` to `images_hq`.  
In the pet: Settings → paths → images dir = `images_hq` (relative to project root).

## Notes

- `images/`, `images_hq/*.png`, and `images_hq_broken/` stay gitignored.
- Large upscales (~hundreds of MB) are intentionally local-only.
- If you skip upscaling, you can point `paths.images_dir` at your original `images/` folder instead (lower res).
