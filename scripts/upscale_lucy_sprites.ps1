# RGBA-safe Lucy sprite upscale (Real-ESRGAN ncnn + alpha merge).
# Source: https://github.com/xinntao/Real-ESRGAN
# Docs: images_hq/README.md
param(
    [int]$Scale = 4,
    [string]$Model = "realesrgan-x4plus-anime",
    [string]$Gpus = "0",
    [switch]$Fresh,
    [switch]$SkipExisting
)

$ErrorActionPreference = "Stop"
$Root = if ($env:LUCY_ROOT) { $env:LUCY_ROOT } else { Split-Path -Parent $PSScriptRoot }
$PyCandidates = @(
    (Join-Path $Root "GPT-SoVITS-v3lora-20250401\runtime\python.exe"),
    "python"
)
$Py = $PyCandidates | Where-Object { $_ -eq "python" -or (Test-Path $_) } | Select-Object -First 1
$Script = Join-Path $Root "scripts\upscale_lucy_sprites_rgba.py"

$argList = @($Script, "--scale", $Scale, "--model", $Model, "--gpus", $Gpus)
if ($Fresh) { $argList += "--fresh" }
if ($SkipExisting) { $argList += "--skip-existing" }
Write-Host "Running RGBA-safe upscale: $Model x$Scale gpus=$Gpus (CPU prep/merge)"
Write-Host "Root: $Root"
& $Py @argList
if ($LASTEXITCODE -ne 0) {
    throw "upscale failed with exit $LASTEXITCODE"
}
Write-Host "Done. Point companion settings paths.images_dir to images_hq"
