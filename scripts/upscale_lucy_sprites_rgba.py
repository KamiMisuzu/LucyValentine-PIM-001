# -*- coding: utf-8 -*-
"""Sharp RGBA-safe Lucy sprite upscale (crop character -> Real-ESRGAN).

Why crop-first:
  - Full 1280x720 frames waste most pixels on empty space
  - realesrgan-x4plus-anime is sharper than animevideov3 but seams on full frames
  - Character crop fits GPU in fewer/cleaner tiles
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from PIL import Image


def _project_root() -> Path:
    env = os.environ.get("LUCY_ROOT", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    # scripts/ -> repo root
    return Path(__file__).resolve().parent.parent


ROOT = _project_root()
EXE = ROOT / "tools" / "realesrgan-ncnn-vulkan" / "realesrgan-ncnn-vulkan.exe"
SRC = ROOT / "images"
OUT = ROOT / "images_hq"
SPRITE_RE = re.compile(r"^Images-l\d+\.png$", re.I)


def _alpha_bbox(im: Image.Image, thr: int = 8, pad: int = 12) -> tuple[int, int, int, int]:
    a = im.split()[-1]
    bbox = a.point(lambda p: 255 if p > thr else 0).getbbox()
    if bbox is None:
        return (0, 0, im.width, im.height)
    x0, y0, x1, y1 = bbox
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(im.width, x1 + pad)
    y1 = min(im.height, y1 + pad)
    return (x0, y0, x1, y1)


def _prepare_one(args: tuple[str, str, str]) -> str:
    src_s, rgb_s, alpha_s = args
    im = Image.open(src_s).convert("RGBA")
    crop = im.crop(_alpha_bbox(im))
    rgb = Image.new("RGB", crop.size, (0, 0, 0))
    alpha = crop.split()[-1]
    rgb.paste(crop, mask=alpha)
    Path(rgb_s).parent.mkdir(parents=True, exist_ok=True)
    Path(alpha_s).parent.mkdir(parents=True, exist_ok=True)
    rgb.save(rgb_s)
    alpha.save(alpha_s)
    return Path(src_s).name


def _merge_one(args: tuple[str, str, str]) -> str:
    rgb_hq_s, alpha_s, dest_s = args
    rgb_hq = Image.open(rgb_hq_s).convert("RGB")
    alpha = Image.open(alpha_s).convert("L")
    alpha_hq = alpha.resize(rgb_hq.size, Image.Resampling.LANCZOS)
    out = Image.merge("RGBA", (*rgb_hq.split(), alpha_hq))
    dest = Path(dest_s)
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.save(dest, optimize=True)
    return dest.name


def _cpu_map(fn, jobs: list, workers: int, label: str) -> None:
    if not jobs:
        return
    workers = max(1, min(workers, len(jobs)))
    print(f"{label}: {len(jobs)} files / {workers} CPU workers", flush=True)
    done = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(fn, job) for job in jobs]
        for fut in as_completed(futs):
            name = fut.result()
            done += 1
            if done % 10 == 0 or done == len(jobs):
                print(f"  {label} {done}/{len(jobs)} ({name})", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=int, default=4)
    ap.add_argument("--model", default="realesrgan-x4plus-anime")
    ap.add_argument("--gpus", default="0,1")
    ap.add_argument("--cpu-workers", type=int, default=max(2, (os.cpu_count() or 4) - 1))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", type=str, default="")
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--skip-existing", action="store_true")
    args = ap.parse_args()

    if not EXE.exists():
        raise SystemExit(f"missing Real-ESRGAN exe: {EXE}")

    files = sorted(p for p in SRC.iterdir() if SPRITE_RE.match(p.name))
    if args.only:
        files = [SRC / args.only]
    if args.limit > 0:
        files = files[: args.limit]
    if not files:
        raise SystemExit("no sprites found")

    broken = ROOT / "images_hq_broken"
    if args.fresh and OUT.exists():
        if broken.exists():
            shutil.rmtree(broken)
        OUT.rename(broken)
    OUT.mkdir(parents=True, exist_ok=True)

    if args.skip_existing:
        before = len(files)
        files = [p for p in files if not (OUT / p.name).exists()]
        print(f"skip-existing: {before - len(files)} done, {len(files)} left", flush=True)
        if not files:
            print(f"done -> {OUT}")
            return

    gpus = args.gpus.strip()
    gpu_list = [g for g in gpus.split(",") if g.strip() != ""]
    if len(gpu_list) >= 2:
        proc = ",".join(["2"] * len(gpu_list))
        jobs_arg = f"2:{proc}:2"
    else:
        jobs_arg = "2:2:2"

    with tempfile.TemporaryDirectory(prefix="lucy_upscale_") as td:
        work = Path(td)
        rgb_dir = work / "rgb"
        alpha_dir = work / "alpha"
        rgb_hq_dir = work / "rgb_hq"
        rgb_dir.mkdir()
        alpha_dir.mkdir()
        rgb_hq_dir.mkdir()

        prep_jobs = [
            (str(src), str(rgb_dir / src.name), str(alpha_dir / f"{src.stem}_a.png"))
            for src in files
        ]
        _cpu_map(_prepare_one, prep_jobs, args.cpu_workers, "CPU crop+prepare")

        print(
            f"GPU upscale: model={args.model} scale={args.scale} gpus={gpus} -j {jobs_arg}",
            flush=True,
        )
        cmd = [
            str(EXE),
            "-i",
            str(rgb_dir),
            "-o",
            str(rgb_hq_dir),
            "-n",
            args.model,
            "-s",
            str(args.scale),
            "-g",
            gpus,
            "-j",
            jobs_arg,
            "-f",
            "png",
            "-v",
        ]
        subprocess.run(cmd, check=True)

        merge_jobs = []
        for src in files:
            rgb_hq = rgb_hq_dir / src.name
            if not rgb_hq.exists():
                alt = next(rgb_hq_dir.glob(f"{src.stem}.*"), None)
                if alt is None:
                    raise FileNotFoundError(f"missing upscaled RGB for {src.name}")
                rgb_hq = alt
            merge_jobs.append(
                (
                    str(rgb_hq),
                    str(alpha_dir / f"{src.stem}_a.png"),
                    str(OUT / src.name),
                )
            )
        _cpu_map(_merge_one, merge_jobs, args.cpu_workers, "CPU merge")

    print(f"done -> {OUT}")


if __name__ == "__main__":
    main()
