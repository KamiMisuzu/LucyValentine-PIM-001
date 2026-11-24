# -*- coding: utf-8 -*-
"""
ReAct loop adapted from baremetal-react/agent.py (MIT License, Copyright 2026 pronzzz).
Lucy-specific: structured final_answer JSON, trace records, history injection.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .backends import LucyLLMBackend
from .registry import ToolRegistry

SYSTEM_TEMPLATE = """{identity}

Keep Lucy the same PERSON through CHANGE (Erikson: continuity amid growth), not a frozen fear script.

You are in a ReAct agent loop.
1) Answer the line「master 在问：…」literally. In thought, restate that ask (who→whom); do not replace it with Lucy's self-intro or growth essay.
2) Prefer final_answer in ONE step for ordinary chat.
3) Call tools when you lack info: get_timeline / get_growth_state / who_am_i / speech_mode_hint / search_memory / get_beijing_time / get_weather / …
4) Do not invent master's identity from random dialog snippets. Hard facts → get_timeline; feelings/bond may color tone only.
5) If 【宿主已查好的天气】 is present, use it. For 现在几点 use get_beijing_time — never treat 「什么时候/最后一次」as wall clock.
6) text (JA) and hint (ZH) must mean the same thing (real gloss, not stage notes).
7) If master attached an image, look at it and answer in Lucy's voice — do not claim you cannot see images.

You must ALWAYS respond with EXACTLY ONE JSON object (no markdown fences).

Format A — tool:
{{
  "thought": "restate ask → why this tool",
  "action": "tool_name",
  "action_input": {{"query": "..."}}
}}

Format B — final Lucy reply:
{{
  "thought": "restate ask → how Lucy answers it",
  "final_answer": {{
    "emotion": "neutral|happy|joyful|shy|surprised|anxious|worried|sad|angry|serious|pleading|affection",
    "text": "（日文台词，ですます；自称ルーシーは/が；称呼マスター）",
    "hint": "（日文的简短中文意思，与 text 同义）"
  }}
}}

Rules:
- Master Chinese → text Japanese; hint Chinese gloss of the same content.
- Characterization (Schechtman): reply must be hers — invent new words; never copy VO verbatim.
- Continuity (Locke/Parfit): connected to shared past; not a generic assistant.

{tools}
"""


@dataclass
class TraceStep:
    iteration: int
    thought: str = ""
    action: str | None = None
    action_input: dict | None = None
    observation: str | None = None
    final_answer: Any = None
    raw: str = ""
    error: str | None = None


@dataclass
class LoopResult:
    final_answer: Any
    trace: list[TraceStep] = field(default_factory=list)
    timed_out: bool = False


def parse_llm_response(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.I).strip()
    text = re.sub(r"<thinking>[\s\S]*?</thinking>", "", text, flags=re.I).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    if "{" in text and not text.startswith("{"):
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            text = m.group(0)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object")
    if "thought" not in data:
        raise ValueError("Missing required key: thought")
    if "action" in data:
        if "action_input" not in data:
            data["action_input"] = {}
    elif "final_answer" not in data:
        raise ValueError("Response must contain either action or final_answer")
    return data


def run_react_loop(
    *,
    user_prompt: str,
    identity: str,
    llm: LucyLLMBackend,
    registry: ToolRegistry,
    model: str,
    temperature: float = 0.5,
    max_iterations: int = 6,
    history: list[dict[str, str]] | None = None,
    debug: bool = False,
    speech_modes: dict[str, Any] | None = None,
    master_text: str = "",
    live_log: Any | None = None,
    image_path: str | None = None,
) -> LoopResult:
    import time as _time

    from ..vision import multimodal_user_content

    # speech_modes / master_text kept for API compat; mode is agent-tool, not host inject
    _ = (speech_modes, master_text)

    def _live(msg: str) -> None:
        if live_log is not None and hasattr(live_log, "live"):
            live_log.live(msg)
        elif debug:
            print(f"[LucyLive] {msg}", flush=True)

    system = SYSTEM_TEMPLATE.format(
        identity=identity.strip(),
        tools=registry.get_system_prompt_segment(),
    )
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    prompt = user_prompt
    if history:
        hist_lines = []
        for h in history[-8:]:
            role = h.get("role", "")
            content = h.get("content", "")
            hist_lines.append(f"{role}: {content}")
        if hist_lines:
            prompt = (
                "Recent dialogue (context only):\n"
                + "\n".join(hist_lines)
                + "\n\n"
                + user_prompt
            )
    user_content = multimodal_user_content(prompt, image_path)
    messages.append({"role": "user", "content": user_content})
    prompt_chars = len(prompt) if isinstance(user_content, str) else len(prompt) + 8
    _live(
        f"react start max_iter={max_iterations} model={model} "
        f"sys_chars={len(system)} prompt_chars={prompt_chars}"
        + (" image=1" if image_path else "")
    )
    trace: list[TraceStep] = []
    for iteration in range(1, max_iterations + 1):
        _live(f"ITER {iteration}/{max_iterations} → calling LLM…")
        t_llm = _time.time()
        raw = llm.generate(messages, model=model, temperature=temperature)
        llm_ms = round((_time.time() - t_llm) * 1000.0, 1)
        _live(f"ITER {iteration} ← LLM done {llm_ms}ms raw_chars={len(raw or '')}")
        step = TraceStep(iteration=iteration, raw=raw)
        try:
            parsed = parse_llm_response(raw)
        except ValueError as e:
            step.error = str(e)
            _live(f"ITER {iteration} PARSE ERROR: {e} | raw_head={(raw or '')[:180]!r}")
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Observation: Parsing Error - {e}\n"
                        "Output only pure JSON with thought + action/final_answer."
                    ),
                }
            )
            trace.append(step)
            continue

        thought = str(parsed.get("thought", ""))
        step.thought = thought
        _live(f"ITER {iteration} thought: {thought[:160]}")
        messages.append({"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)})

        if "final_answer" in parsed:
            from .critic import _unwrap_payload

            fa = parsed["final_answer"]
            if isinstance(fa, str):
                try:
                    fa_obj = json.loads(fa)
                except json.JSONDecodeError:
                    fa_obj = {"text": fa}
            elif isinstance(fa, dict):
                fa_obj = fa
            else:
                fa_obj = {"text": str(fa)}
            fa_obj = _unwrap_payload(fa_obj)
            text_val = str(fa_obj.get("text") or "").strip()
            bad = (
                not text_val
                or text_val.startswith("{")
                or '"emotion"' in text_val
            )
            if bad:
                # one retry budget: if we already rejected format once, salvage JP substring
                prior_bad = sum(1 for t in trace if t.error == "bad_final_format")
                salvaged = None
                m = re.search(
                    r"([ァ-ヶーぁ-ん一-龥A-Za-z0-9、。…！？!?「」『』（）\s]{8,})",
                    text_val,
                )
                if m:
                    salvaged = m.group(1).strip(" \"'\\n{}:")
                if prior_bad >= 1 and salvaged:
                    fa_obj["text"] = salvaged
                    if not fa_obj.get("hint"):
                        fa_obj["hint"] = ""
                    step.final_answer = fa_obj
                    trace.append(step)
                    _live(f"ITER {iteration} FINAL salvaged: {salvaged[:120]}")
                    return LoopResult(final_answer=fa_obj, trace=trace)
                obs = (
                    "Error - final_answer.text must be ONE plain Japanese line "
                    "(no nested JSON). Retry final_answer only."
                )
                step.observation = obs
                step.error = "bad_final_format"
                step.final_answer = fa_obj
                _live(f"ITER {iteration} bad_final_format text_head={text_val[:120]!r}")
                messages.append({"role": "user", "content": f"Observation: {obs}"})
                trace.append(step)
                continue
            step.final_answer = fa_obj
            _ft = str(fa_obj.get("text") or "")
            _fh = str(fa_obj.get("hint") or "")
            _live(
                f"ITER {iteration} FINAL emo={fa_obj.get('emotion')} "
                f"text_chars={len(_ft)} hint_chars={len(_fh)} "
                f"text={_ft!r} hint={_fh!r}"
            )
            trace.append(step)
            return LoopResult(final_answer=fa_obj, trace=trace)

        action = str(parsed.get("action", ""))
        action_input = parsed.get("action_input") or {}
        if not isinstance(action_input, dict):
            action_input = {"query": str(action_input)}
        step.action = action
        step.action_input = action_input
        _live(f"ITER {iteration} ACTION {action} {json.dumps(action_input, ensure_ascii=False)[:120]}")

        tool = registry.get_tool(action)
        t_tool = _time.time()
        if not tool:
            obs = f"Error - Tool '{action}' not found. Available: {registry.names()}"
        else:
            obs = tool.call(action_input)
        tool_ms = round((_time.time() - t_tool) * 1000.0, 1)
        step.observation = obs
        _live(f"ITER {iteration} OBS {tool_ms}ms: {(obs or '')[:220]}")
        messages.append({"role": "user", "content": f"Observation: {obs}"})
        trace.append(step)

    _live(f"react TIMED OUT after {max_iterations} iters")
    return LoopResult(
        final_answer={
            "emotion": "anxious",
            "text": "あの…ルーシー、もう少し考えてもよろしいですか？",
            "hint": "那个…能再让 Lucy 想一下吗？",
        },
        trace=trace,
        timed_out=True,
    )
