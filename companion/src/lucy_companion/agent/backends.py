# -*- coding: utf-8 -*-
"""LLM backend adapter — bridges Lucy LLMClient to the ReAct loop."""
from __future__ import annotations

from ..llm.client import LLMClient


class LucyLLMBackend:
    """OpenAI-compatible generate() used by the ReAct loop."""

    def __init__(
        self,
        client: LLMClient,
        *,
        max_tokens: int | None = None,
        no_think: bool = True,
    ):
        self.client = client
        self.max_tokens = max_tokens
        # Qwen3: skip hidden chain-of-thought; JSON "thought" field still used
        self.no_think = bool(no_think)

    def generate(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float | None = None,
    ) -> str:
        msgs = list(messages)
        if self.no_think and msgs:
            # Prepend /no_think to system so Ollama/Qwen3 skips long hidden think
            first = dict(msgs[0])
            content = first.get("content")
            if isinstance(content, str) and not content.lstrip().startswith("/no_think"):
                first["content"] = "/no_think\n" + content
                msgs[0] = first
            elif isinstance(content, list):
                # Multimodal: put /no_think on first text part
                parts = list(content)
                for i, p in enumerate(parts):
                    if isinstance(p, dict) and p.get("type") == "text":
                        t = str(p.get("text") or "")
                        if not t.lstrip().startswith("/no_think"):
                            parts[i] = {**p, "text": "/no_think\n" + t}
                        break
                first["content"] = parts
                msgs[0] = first
        # API-level think=false — qwen3 on Ollama ignores /no_think text alone
        return self.client.chat(
            msgs,
            model=model,
            think=False if self.no_think else None,
            max_tokens=self.max_tokens,
            temperature=temperature,
        )
