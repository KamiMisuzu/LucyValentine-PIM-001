# Lucy Companion (package)

See the [root README](../README.md) for install, LLM/voice setup, and license.

```text
companion/
  config/           # personas, examples — copy settings.example.yaml → settings.yaml
  data/             # runtime memories / sessions (many files gitignored)
  src/lucy_companion/
  scripts/          # chat_lucy.py, run_desktop_lucy.py
  assets/           # fonts / icons for the pet UI
```

```powershell
cd companion
python -m pip install -r requirements.txt
copy config\settings.example.yaml config\settings.yaml
$env:PYTHONPATH = "$PWD\src"
python scripts\run_desktop_lucy.py
```
