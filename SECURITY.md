# Security

## API keys

- Put keys in environment variables (`llm.api_key_env`), not in git.
- `companion/config/settings.yaml` is gitignored. If a key was ever committed or pasted into chat, **rotate it** at the provider console immediately.

## What not to publish

- Personal session logs (`companion/data/sessions/`)
- `personal_memories.jsonl`, power / emotion runtime state
- Game sprites, voice corpora, fine-tuned `.pth` / `.ckpt` weights (third-party IP)

## Reporting

If you find a vulnerability in this software, open a private report with the maintainer (do not file a public issue with exploit details).
