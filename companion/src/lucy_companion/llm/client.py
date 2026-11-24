# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from openai import OpenAI

from ..config import Settings


class LLMClient:
    """Thin LLM wrapper — OpenAI-compatible, with native Ollama path for qwen3."""

    def __init__(self, settings: Settings):
        self.settings = settings
        llm = settings.llm
        self._client: OpenAI | None = None
        self.model = str(llm.get("model", "deepseek-chat"))
        self.rewrite_model = str(llm.get("rewrite_model") or self.model)
        # Image+text: qwen3.8-flash is already multimodal — default = chat model
        self.vision_model = str(llm.get("vision_model") or self.model)
        self.temperature = float(llm.get("temperature", 0.7))
        self.max_tokens = int(llm.get("max_tokens", 400))
        self.rewrite_enabled = bool(llm.get("rewrite_enabled", True))
        self.base_url = str(llm.get("base_url", "https://api.deepseek.com"))
        # Qwen3-on-Ollama: disable hidden CoT (OpenAI /v1 leaves content empty in reasoning)
        self.think = bool(llm.get("think", False))
        self.num_predict = llm.get("num_predict")  # optional hard cap
        self._ollama_native = self._detect_ollama(self.base_url, llm)
        self._usage_hooks: list[Callable[[int], None]] = []

    def add_usage_hook(self, fn: Callable[[int], None]) -> None:
        """Notify local power meter (etc.) after each LLM call."""
        if fn and fn not in self._usage_hooks:
            self._usage_hooks.append(fn)

    def reload_from_settings(self) -> None:
        """Re-read llm.* after settings dialog save (drops cached OpenAI client)."""
        llm = self.settings.llm
        self.model = str(llm.get("model", self.model))
        self.rewrite_model = str(llm.get("rewrite_model") or self.model)
        self.vision_model = str(llm.get("vision_model") or self.model)
        self.temperature = float(llm.get("temperature", self.temperature))
        self.max_tokens = int(llm.get("max_tokens", self.max_tokens))
        self.rewrite_enabled = bool(llm.get("rewrite_enabled", self.rewrite_enabled))
        self.base_url = str(llm.get("base_url", self.base_url))
        self.think = bool(llm.get("think", self.think))
        self.num_predict = llm.get("num_predict")
        self._ollama_native = self._detect_ollama(self.base_url, llm)
        self._client = None

    def _emit_usage(self, tokens: int) -> None:
        n = max(0, int(tokens or 0))
        if n <= 0:
            return
        for fn in self._usage_hooks:
            try:
                fn(n)
            except Exception:
                pass

    @staticmethod
    def _estimate_tokens(messages: list[dict[str, Any]], content: str) -> int:
        parts: list[str] = []
        for m in messages:
            c = m.get("content")
            if isinstance(c, str):
                parts.append(c)
            elif isinstance(c, list):
                for p in c:
                    if isinstance(p, dict) and p.get("type") == "text":
                        parts.append(str(p.get("text") or ""))
                    elif isinstance(p, dict) and p.get("type") == "image_url":
                        parts.append("[image]")
        parts.append(content or "")
        blob = "".join(parts)
        # Rough CJK-friendly estimate when provider omits usage
        return max(1, len(blob) // 2)

    @staticmethod
    def _messages_need_vision(messages: list[dict[str, Any]]) -> bool:
        from ..vision import content_has_image

        return any(content_has_image(m.get("content")) for m in messages)

    @staticmethod
    def _detect_ollama(base_url: str, llm: dict[str, Any]) -> bool:
        if llm.get("use_ollama_native") is False:
            return False
        if str(llm.get("provider") or "").lower() == "ollama":
            return True
        u = (base_url or "").lower()
        return "11434" in u or "ollama" in u

    def _ollama_chat_url(self) -> str:
        """Map http://host:11434/v1 → http://host:11434/api/chat"""
        raw = self.base_url.rstrip("/")
        if raw.endswith("/v1"):
            raw = raw[:-3]
        parsed = urlparse(raw if "://" in raw else f"http://{raw}")
        root = f"{parsed.scheme}://{parsed.netloc}"
        return f"{root}/api/chat"

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                api_key=self.settings.api_key(),
                base_url=self.base_url,
            )
        return self._client

    def chat(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        think: bool | None = None,
    ) -> str:
        use_think = self.think if think is None else bool(think)
        max_tok = self.max_tokens if max_tokens is None else int(max_tokens)
        temp = self.temperature if temperature is None else float(temperature)
        need_vision = self._messages_need_vision(messages)
        if model:
            model_name = model
        elif need_vision:
            model_name = self.vision_model or self.model
        else:
            model_name = self.model

        if self._ollama_native:
            if need_vision:
                # Most local 8B installs are text-only; strip images to a text stub
                messages = self._strip_images_for_text(messages)
            return self._chat_ollama_native(
                messages,
                model=model_name,
                max_tokens=max_tok,
                temperature=temp,
                think=use_think,
            )

        # Cloud OpenAI-compatible: do not send Ollama-only think/options
        resp = self.client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=temp,
            max_tokens=max_tok,
        )
        msg = resp.choices[0].message
        content = (msg.content or "").strip()
        if not content:
            reasoning = getattr(msg, "reasoning", None) or ""
            if isinstance(reasoning, str) and reasoning.strip():
                content = reasoning.strip()
        usage = getattr(resp, "usage", None)
        total = int(getattr(usage, "total_tokens", 0) or 0) if usage else 0
        if total <= 0:
            total = self._estimate_tokens(messages, content)
        self._emit_usage(total)
        return content

    @staticmethod
    def _strip_images_for_text(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            c = m.get("content")
            if not isinstance(c, list):
                out.append(m)
                continue
            texts = [
                str(p.get("text") or "")
                for p in c
                if isinstance(p, dict) and p.get("type") == "text"
            ]
            has_img = any(
                isinstance(p, dict) and p.get("type") == "image_url" for p in c
            )
            text = "\n".join(t for t in texts if t).strip()
            if has_img:
                text = (text + "\n（master 发来一张图片，但当前本地模型看不了图）").strip()
            out.append({**m, "content": text or "（图片）"})
        return out

    def _chat_ollama_native(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        max_tokens: int,
        temperature: float,
        think: bool,
    ) -> str:
        """Native /api/chat — only place think:false reliably fills message.content for qwen3."""
        predict = int(self.num_predict) if self.num_predict is not None else int(max_tokens)
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": bool(think),
            "options": {
                "temperature": float(temperature),
                "num_predict": predict,
            },
        }
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self._ollama_chat_url(),
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise RuntimeError(f"ollama /api/chat HTTP {exc.code}: {detail}") from exc
        msg = payload.get("message") or {}
        content = str(msg.get("content") or "").strip()
        if not content:
            # Rare: thinking still leaked
            thinking = str(msg.get("thinking") or "").strip()
            if thinking and "{" in thinking:
                content = thinking
        total = int(payload.get("prompt_eval_count") or 0) + int(
            payload.get("eval_count") or 0
        )
        if total <= 0:
            total = self._estimate_tokens(messages, content)
        self._emit_usage(total)
        return content

    def translate_ja_to_zh_hint(self, ja_text: str) -> str:
        """Short Chinese gloss for the Japanese line (never meta commentary)."""
        from .style_filter import is_meta_hint, sanitize_speech_text

        ja_text = sanitize_speech_text(ja_text or "")
        if not ja_text:
            return ""
        messages = [
            {
                "role": "system",
                "content": (
                    "/no_think\n"
                    "把下面日文台词译成一句简短通顺的中文白话，让人听懂她在说什么。"
                    "只输出译文本身：不要引号，不要解释，不要写情绪分析、写作备注、动机或‘存在感/安全感’这类导演词。"
                ),
            },
            {"role": "user", "content": ja_text},
        ]
        raw = self.chat(messages, max_tokens=120, temperature=0.2, think=False)
        # strip accidental wrappers
        for a, b in (("```", ""), ("「", ""), ("」", ""), ('"', ""), ("“", ""), ("”", "")):
            raw = raw.replace(a, b)
        gloss = raw.strip().splitlines()[0].strip() if raw.strip() else ""
        return "" if is_meta_hint(gloss) else gloss

    def rewrite_as_lucy(self, draft_text: str, persona: str) -> str:
        if not self.rewrite_enabled:
            return draft_text
        messages = [
            {
                "role": "system",
                "content": (
                    persona
                    + "\n\n你现在只做改写：把下面草稿改成 Lucy 的语气。"
                    + "保持原意，删掉 AI 腔和网感甜话。"
                    + "text 必须是日文台词；hint 必须是简短中文提示。"
                    + "仍然只输出 JSON："
                    + '{"emotion":"...","text":"（日文）","hint":"（中文提示）"}'
                ),
            },
            {"role": "user", "content": draft_text},
        ]
        return self.chat(messages, model=self.rewrite_model)
