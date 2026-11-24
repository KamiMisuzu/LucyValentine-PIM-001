#Requires -Version 5.1
<#
.SYNOPSIS
  One-click init for Lucy Companion: paths, settings.yaml, folders, dependency check.
.NOTES
  Does not train TTS. Only prepares runtime paths for inference.
#>
param(
  [string]$ApiKeyEnv = "QIANWEN_API_KEY",
  [switch]$SkipPip
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Root "companion\src\lucy_companion"))) {
  Write-Error "Cannot find companion package under $Root"
}

Write-Host "== Lucy Companion setup ==" -ForegroundColor Cyan
Write-Host "Root: $Root"

function Ensure-Dir([string]$Rel) {
  $p = Join-Path $Root $Rel
  if (-not (Test-Path $p)) {
    New-Item -ItemType Directory -Path $p | Out-Null
    Write-Host "  + dir  $Rel"
  } else {
    Write-Host "  · dir  $Rel"
  }
  return $p
}

# Runtime folders
Ensure-Dir "output\companion_voice" | Out-Null
Ensure-Dir "companion\data\sessions" | Out-Null
Ensure-Dir "companion\data\debug" | Out-Null
Ensure-Dir "voice_models" | Out-Null
Ensure-Dir "images_hq" | Out-Null

# settings.yaml from example
$cfgDir = Join-Path $Root "companion\config"
$example = Join-Path $cfgDir "settings.example.yaml"
$settings = Join-Path $cfgDir "settings.yaml"
if (-not (Test-Path $example)) {
  Write-Error "Missing $example"
}
if (-not (Test-Path $settings)) {
  Copy-Item $example $settings
  Write-Host "  + wrote companion\config\settings.yaml from example"
} else {
  Write-Host "  · keep existing settings.yaml"
}

# Rewrite portable paths inside settings.yaml (PyYAML-less: careful line replace)
$gsvCandidates = @(
  "GPT-SoVITS-v3lora-20250401",
  "GPT_SoVITS"
) | ForEach-Object { Join-Path $Root $_ } | Where-Object { Test-Path $_ }

$gsvRel = $null
$pyExe = $null
foreach ($c in @(
    "GPT-SoVITS-v3lora-20250401\runtime\python.exe",
    "GPT-SoVITS-v3lora-20250401\runtime\python",
    "GPT_SoVITS\runtime\python.exe"
  )) {
  $full = Join-Path $Root $c
  if (Test-Path $full) {
    $pyExe = $c -replace "\\", "/"
    $gsvRel = ($c -split "[\\/]")[0]
    break
  }
}

$text = Get-Content $settings -Raw -Encoding UTF8
# project_root → .
$text = [regex]::Replace($text, '(?m)^project_root:\s*.*$', 'project_root: .')
# voice worker / python relative
$text = [regex]::Replace(
  $text,
  '(?m)^(\s*)worker_script:\s*.*$',
  '${1}worker_script: scripts/companion_tts_worker.py'
)
if ($pyExe) {
  $text = [regex]::Replace(
    $text,
    '(?m)^(\s*)python_exe:\s*.*$',
    "`${1}python_exe: $pyExe"
  )
  Write-Host "  + voice.python_exe → $pyExe"
} else {
  Write-Host "  ! GPT-SoVITS runtime python not found — set voice.python_exe later" -ForegroundColor Yellow
}
# empty api_key so env is used
if ($text -notmatch '(?m)^(\s*)api_key:\s*""\s*$') {
  $text = [regex]::Replace($text, '(?m)^(\s*)api_key:\s*.*$', '${1}api_key: ""')
}
$text = [regex]::Replace($text, '(?m)^(\s*)api_key_env:\s*.*$', "`${1}api_key_env: $ApiKeyEnv")

Set-Content -Path $settings -Value $text -Encoding UTF8
Write-Host "  + normalized paths in settings.yaml"

# Weight presence (inference only — no training)
$weightHints = @(
  "GPT-SoVITS-v3lora-20250401\GPT_weights_v3\lucy-e10.ckpt",
  "GPT-SoVITS-v3lora-20250401\SoVITS_weights_v3\lucy_e2_s1904_l32.pth"
)
$haveWeights = $true
foreach ($w in $weightHints) {
  $wp = Join-Path $Root $w
  if (Test-Path $wp) {
    Write-Host "  · weight $($w.Split('\')[-1])"
  } else {
    $haveWeights = $false
    Write-Host "  ! missing $w (see voice_models\README.md)" -ForegroundColor Yellow
  }
}

# personal memories stub
$pm = Join-Path $Root "companion\data\personal_memories.jsonl"
if (-not (Test-Path $pm)) {
  New-Item -ItemType File -Path $pm | Out-Null
  Write-Host "  + empty personal_memories.jsonl"
}

if (-not $SkipPip) {
  Write-Host "  · pip install companion requirements…"
  $req = Join-Path $Root "companion\requirements.txt"
  python -m pip install -r $req
  if ($LASTEXITCODE -ne 0) {
    Write-Host "  ! pip failed — install manually: python -m pip install -r companion\requirements.txt" -ForegroundColor Yellow
  }
}

# smoke: import package
$env:PYTHONPATH = Join-Path $Root "companion\src"
$env:LUCY_ROOT = $Root
Write-Host "  · import check…"
python -c "from lucy_companion.config import load_settings; s=load_settings(); print('project_root=', s.project_root)"
if ($LASTEXITCODE -ne 0) {
  Write-Host "  ! import failed" -ForegroundColor Red
  exit 1
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "Next:"
Write-Host "  1) Set API key:  `$env:$ApiKeyEnv = 'your-key'   (or edit settings.yaml locally)"
if (-not $haveWeights) {
  Write-Host "  2) Put inference weights in place — voice_models\README.md (no training docs here)"
}
Write-Host "  3) Run:  powershell -File scripts\setup_lucy.ps1   # already done"
Write-Host "     then: python scripts\run_desktop_lucy.py"
Write-Host ""
Write-Host "Git tip: commits must use YOUR name/email, not Cursor's." -ForegroundColor DarkGray
Write-Host "  git config user.name  `"Your Name`""
Write-Host "  git config user.email `"you@example.com`""
