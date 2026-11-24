# -*- coding: utf-8 -*-
"""High-level LucyAgent API used by pipeline / debug scripts."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import Settings
from ..llm.client import LLMClient
from ..llm.style_filter import enforce_lucy_style, parse_lucy_json
from ..memory.canon import CanonMemoryStore
from ..memory.personal import PersonalMemoryStore
from ..timeline import MasterTimeline, render_template
from .backends import LucyLLMBackend
from .critic import criticize_and_fix
from .jp_index import JpLineIndex
from .loop import LoopResult, run_react_loop
from .memory_index import PersonalityStore, get_retriever, load_jsonl_cards, set_retrieval_context
from .tools_lucy import (
    ToolContext,
    build_lucy_registry,
    load_speech_modes,
    suggest_mode,
)
from ..personality.author import load_author_live, merge_author_into_identity
from ..personality.ledger import PersonalityLedger, load_event_map
from ..personality.sync import format_motives_block, merge_stages


@dataclass
class AgentResult:
    payload: dict[str, Any]
    trace: list[Any] = field(default_factory=list)
    timed_out: bool = False
    critic_applied: bool = False
    debug: dict[str, Any] | None = None


def _coerce_final(final: Any) -> dict[str, Any]:
    from .critic import _unwrap_payload

    if isinstance(final, dict) and "text" in final:
        return _unwrap_payload(final)
    if isinstance(final, str):
        return _unwrap_payload(parse_lucy_json(final))
    return _unwrap_payload(parse_lucy_json(json.dumps(final, ensure_ascii=False)))


def _resolve_path(root: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (root / p)


class LucyAgent:
    def __init__(
        self,
        settings: Settings,
        *,
        llm: LLMClient | None = None,
        canon: CanonMemoryStore | None = None,
        personal: PersonalMemoryStore | None = None,
        timeline: MasterTimeline | None = None,
        user_address: str = "master",
        growth_snapshot: dict[str, Any] | None = None,
    ):
        self.settings = settings
        self.llm = llm or LLMClient(settings)
        self.user_address = user_address
        self.timeline = timeline
        self._growth_snapshot = dict(growth_snapshot or {})

        agent_cfg = settings.raw.get("agent") or {}
        self.enabled = bool(agent_cfg.get("enabled", True))
        self.max_iterations = int(agent_cfg.get("max_iterations", 8))
        self.debug_trace = bool(agent_cfg.get("debug_trace", False))
        self.temperature = float(agent_cfg.get("temperature", 0.5))
        self.max_tokens = int(agent_cfg.get("max_tokens", 900))
        self.critic_enabled = bool(agent_cfg.get("critic_enabled", True))

        paths = settings.paths
        root = settings.project_root

        persona_path = settings.path("persona")
        agent_sys = paths.get("agent_system", "companion/config/lucy_agent_system.txt")
        agent_sys_path = _resolve_path(root, str(agent_sys))
        self._identity_raw = ""
        if agent_sys_path.exists():
            self._identity_raw = agent_sys_path.read_text(encoding="utf-8")
        elif persona_path.exists():
            self._identity_raw = persona_path.read_text(encoding="utf-8")

        self.canon = canon or CanonMemoryStore(settings.path("canon_memories"))
        self.personal = personal or PersonalMemoryStore(settings.path("personal_memories"))

        jp_path = _resolve_path(
            root,
            str(
                paths.get(
                    "jp_lines",
                    "GPT-SoVITS-v3lora-20250401/output/asr_opt/lucy_jp_clean.list",
                )
            ),
        )
        if not jp_path.exists():
            alt = root / "GPT-SoVITS-v3lora-20250401/output/asr_opt/lucy_jp.list"
            if alt.exists():
                jp_path = alt
        self.jp_index = JpLineIndex(jp_path)

        modes_path = _resolve_path(
            root, str(paths.get("speech_modes", "companion/config/speech_modes.json"))
        )
        self.speech_modes = load_speech_modes(modes_path)

        pers_path = _resolve_path(
            root,
            str(paths.get("personality_cards", "companion/data/lucy_personality_cards.jsonl")),
        )
        self.personality = PersonalityStore(pers_path)

        ep_path = _resolve_path(
            root,
            str(paths.get("shared_episodes", "companion/data/shared_episodes.jsonl")),
        )
        # Fall back to canon cards if shared_episodes missing
        self.episode_cards = load_jsonl_cards(ep_path) if ep_path.exists() else list(self.canon.cards)

        id_path = _resolve_path(
            root, str(paths.get("identity", "companion/config/lucy_identity.json"))
        )
        self._identity_path = id_path
        self._identity_seed: dict[str, Any] = {}
        if id_path.exists():
            self._identity_seed = json.loads(id_path.read_text(encoding="utf-8"))
        self.identity: dict[str, Any] = dict(self._identity_seed)
        author_live = paths.get("author_live", "companion/data/lucy_author_live.json")
        self._author_live_path = _resolve_path(root, str(author_live))

        events_path = _resolve_path(
            root, str(paths.get("life_events", "companion/data/lucy_life_events.jsonl"))
        )
        map_path = _resolve_path(
            root,
            str(
                paths.get(
                    "personality_event_map",
                    "companion/config/personality_event_map.json",
                )
            ),
        )
        affect_path = _resolve_path(
            root, str(paths.get("affect_curves", "companion/config/affect_curves.json"))
        )
        # Merge Author before ledger so baselines see live story context if needed
        live = load_author_live(self._author_live_path)
        self.identity = merge_author_into_identity(dict(self._identity_seed), live)
        self.personality_ledger = PersonalityLedger(
            events_path,
            identity=self.identity,
            event_map=load_event_map(map_path),
            affect_curves_path=affect_path if affect_path.exists() else None,
        )

        science_path = _resolve_path(
            root,
            str(
                paths.get(
                    "human_memory_science",
                    "companion/config/human_memory_science.json",
                )
            ),
        )
        get_retriever(science_path if science_path.exists() else None)

        self.tool_ctx = ToolContext(
            history=[],
            timeline=self.timeline,
            user_address=self.user_address,
            identity=self.identity,
            growth=dict(self._growth_snapshot),
            ledger=self.personality_ledger,
            author_live_path=self._author_live_path,
        )

        mem = settings.memory
        self.force_motives_in_prompt = bool(agent_cfg.get("force_motives_in_prompt", True))
        self.strip_vocative = bool(agent_cfg.get("strip_vocative", True))
        self.ask_frame = bool(agent_cfg.get("ask_frame", True))
        # Intentional nicknames only — typos are fuzzy-matched, not listed
        self.vocative_aliases = [
            str(x).strip()
            for x in (agent_cfg.get("vocative_aliases") or [])
            if str(x).strip()
        ]
        self.registry = build_lucy_registry(
            canon=self.canon,
            personal=self.personal,
            jp_index=self.jp_index,
            speech_modes=self.speech_modes,
            personality=self.personality,
            episode_cards=self.episode_cards,
            ctx=self.tool_ctx,
            identity=self.identity,
            ledger=self.personality_ledger,
            canon_top_k=int(mem.get("canon_top_k", 6)),
            personal_top_k=int(mem.get("personal_top_k", 4)),
            jp_top_k=int(agent_cfg.get("jp_top_k", 5)),
        )
        self.backend = LucyLLMBackend(
            self.llm,
            max_tokens=self.max_tokens,
            no_think=bool(agent_cfg.get("no_think", True)),
        )
        self._default_weather_city = str(
            (settings.chat or {}).get("default_weather_city", "南宁")
        )
        # Host prefetch: local Ollama wants time+weather; cloud usually weather-only
        world_cfg = dict(settings.raw.get("world") or {})
        base = str(settings.llm.get("base_url") or "")
        provider = str(settings.llm.get("provider") or "").lower()
        local_llm = provider == "ollama" or "11434" in base or "ollama" in base.lower()
        if "prefetch_time" in world_cfg:
            self.prefetch_time = bool(world_cfg.get("prefetch_time"))
        else:
            self.prefetch_time = local_llm
        if "prefetch_weather" in world_cfg:
            self.prefetch_weather = bool(world_cfg.get("prefetch_weather"))
        else:
            self.prefetch_weather = True

    def refresh_identity_author(self, live_path: Path | None = None) -> None:
        """Merge live Author rewrite into identity seen by tools / who_am_i."""
        path = live_path or self._author_live_path
        live = load_author_live(path)
        self.identity = merge_author_into_identity(dict(self._identity_seed), live)
        if getattr(self, "tool_ctx", None) is not None:
            self.tool_ctx.identity = self.identity
        if getattr(self, "personality_ledger", None) is not None:
            self.personality_ledger.identity = self.identity

    def set_growth_snapshot(self, snap: dict[str, Any] | None) -> None:
        self._growth_snapshot = dict(snap or {})
        merged = dict(self._growth_snapshot)
        # Overlay event-replay personality so tools see one coherent growth view.
        goals: dict[str, float] = {}
        try:
            pers = self.personality_ledger.snapshot_for_growth()
            merged["personality_from_events"] = pers
            g_stage = str(merged.get("growth_stage") or merged.get("stage") or "")
            l_stage = str(pers.get("stage") or pers.get("stage_hint") or "")
            if merged.get("stage") and l_stage:
                merged["stage"] = merge_stages(str(merged["stage"]), l_stage)
            elif l_stage:
                merged["stage"] = merge_stages(g_stage or "fragile_new", l_stage)
            goals = {
                str(k): float(v) for k, v in dict(pers.get("motives") or {}).items()
            }
        except Exception:
            pass
        self.tool_ctx.growth = merged
        self.tool_ctx.ledger = self.personality_ledger
        # Conway working-self gates for autobiographical retrieval
        sec = merged.get("security")
        try:
            security = float(sec) / 100.0 if sec is not None and float(sec) > 1.5 else float(sec or 0.3)
        except (TypeError, ValueError):
            security = 0.3
        set_retrieval_context(
            security=security,
            attachment_activation=float(merged.get("attachment") or 0.2),
            active_goals=goals,
        )

    def identity_text(self) -> str:
        text = self._identity_raw
        if self.timeline is not None:
            text = render_template(text, self.timeline, address=self.user_address)
        # Append live self_story so ReAct system sees evolving Author
        author = dict(self.identity.get("L3_author") or {})
        story = str(author.get("self_story") or "").strip()
        if story:
            text = text.rstrip() + f"\n\n【Author 此刻】{story}\n"
        return text

    def ask(
        self,
        user_text: str,
        history: list[dict[str, str]] | None = None,
        *,
        debug: bool | None = None,
        image_path: str | None = None,
    ) -> AgentResult:
        from ..debug_turn import TurnDebug, echo_ratio
        from ..llm.style_filter import is_meta_hint, sanitize_speech_text
        from ..world.prefetch import prefetch_world_facts

        debug = self.debug_trace if debug is None else debug
        dbg = TurnDebug(user_text=user_text)
        dbg.mark("ask_start")
        # Live step log — readable while still thinking
        live = getattr(self, "_live_log", None)
        if live is None:
            from ..debug_turn import TurnDebugLog

            live = TurnDebugLog(
                self.settings.project_root,
                enabled=bool((self.settings.chat or {}).get("debug_log", True)),
            )
            self._live_log = live
        live.live_clear_turn(user_text)
        identity = self.identity_text()
        history = history or []

        # --- Ask normalize: strip UI vocative; optional same-model frame ---
        from .ask_frame import format_frame_block, frame_ask, strip_vocative

        body = user_text
        stripped = False
        if self.strip_vocative:
            body, stripped = strip_vocative(
                user_text, aliases=self.vocative_aliases
            )
        frame: dict[str, Any] = {}
        frame_block = ""
        if self.ask_frame:
            t_fr = __import__("time").perf_counter()
            try:
                frame = frame_ask(self.llm, raw=user_text, body=body)
                frame_block = format_frame_block(frame)
                ms = (__import__("time").perf_counter() - t_fr) * 1000
                live.live(
                    f"ask_frame {ms:.0f}ms stripped={stripped} "
                    f"ask_zh={(frame.get('ask_zh') or '')[:60]}"
                )
                dbg.note(
                    f"ask_frame stripped={stripped} ask_zh={frame.get('ask_zh')!r}"
                )
            except Exception as exc:
                dbg.errors.append(f"ask_frame: {exc}")
                live.live(f"ask_frame skip: {exc}")
        elif stripped:
            live.live(f"vocative stripped → {body!r}")
            dbg.note(f"vocative stripped → {body!r}")

        # Keep tool closures in sync (retrieval uses body without name prefix)
        self.tool_ctx.history = list(history)
        self.tool_ctx.timeline = self.timeline
        self.tool_ctx.user_address = self.user_address
        self.tool_ctx.identity = self.identity
        set_retrieval_context(query=body)

        # Mode is agent-side (speech_mode_hint tool), not host keyword tagging
        suggested = suggest_mode(body, self.speech_modes)
        stage = str((self.tool_ctx.growth or {}).get("stage") or "")
        motives_line = ""
        if self.force_motives_in_prompt:
            try:
                pers = self.personality_ledger.snapshot_for_growth()
                motives_line = format_motives_block(pers) + "\n"
            except Exception as exc:
                dbg.errors.append(f"motives: {exc}")
                motives_line = ""
        ask_zh = str((frame or {}).get("ask_zh") or "").strip()
        ask_line = ask_zh or body

        # Host prefetch (time optional — on for local Ollama, off for cloud by default)
        world = prefetch_world_facts(
            body,
            default_city=self._default_weather_city,
            prefetch_time=self.prefetch_time,
            prefetch_weather=self.prefetch_weather,
        )
        dbg.prefetch = {
            "needs": world.get("needs"),
            "ok": world.get("ok"),
            "time_ok": (world.get("time") or {}).get("ok"),
            "weather_ok": (world.get("weather") or {}).get("ok"),
            "stock_ok": (world.get("stock") or {}).get("ok"),
            "weather_summary": (world.get("weather") or {}).get("summary_zh"),
            "time_display": (world.get("time") or {}).get("display_zh"),
            "stock_summary": (world.get("stock") or {}).get("summary_zh"),
            "prefetch_time": self.prefetch_time,
            "prefetch_weather": self.prefetch_weather,
        }
        if world.get("ok"):
            dbg.note("host prefetch world facts injected")
            live.live(
                f"prefetch ok time={dbg.prefetch.get('time_display')} "
                f"wx={dbg.prefetch.get('weather_summary')}"
            )
        else:
            live.live(f"prefetch skip needs={dbg.prefetch.get('needs')}")
        dbg.mark("prefetch_done")

        facts_ready = self._world_facts_ready(world)
        loop: LoopResult | None = None
        critic_applied = False
        emergency = False
        payload: dict[str, Any]

        if facts_ready:
            live.live("FAST PATH: world facts ready → single-shot (skip ReAct)")
            dbg.note("fact_fast_path")
            t_fast = __import__("time").perf_counter()
            try:
                payload = self._fact_aware_rewrite(
                    body,
                    world.get("prompt_block") or "",
                    suggested,
                    world=world,
                )
                ms = (__import__("time").perf_counter() - t_fast) * 1000
                live.live(f"FAST PATH done {ms:.0f}ms text={(payload.get('text') or '')[:80]}")
                dbg.react_iters = 0
                dbg.timed_out = False
                dbg.echo_rewrite = True  # used fact rewriter as primary
            except Exception as exc:
                dbg.errors.append(f"fact_fast_path: {exc}")
                live.live(f"FAST PATH failed → template/ReAct: {exc}")
                try:
                    payload = self._fact_template_from_world(world)
                    dbg.note("fact_template_fallback")
                    dbg.react_iters = 0
                    dbg.timed_out = False
                except Exception:
                    facts_ready = False

        if not facts_ready:
            prompt = (
                f"master（称呼={self.user_address}）在问：{ask_line}\n"
                f"（原话：{user_text}）\n"
                f"{motives_line}"
                f"{world.get('prompt_block') or ''}"
                "直接答上面的问句。需要动机/成长再 call get_growth_state 或 who_am_i；"
                "需要时间线 call get_timeline；口调 call speech_mode_hint。"
                "不要背原作，不要变成通用助手。"
                "重大共享事件多半已自动记入；仅漏记时才 append_life_event。"
            )
            live.live("entering react loop…")
            react_model = str(self.settings.llm.get("model", "qwen3:8b"))
            if image_path:
                react_model = str(
                    self.settings.llm.get("vision_model")
                    or getattr(self.llm, "vision_model", None)
                    or react_model
                )
                live.live(f"image+text → model={react_model}")
                dbg.note(f"image={image_path}")
            loop = run_react_loop(
                user_prompt=prompt,
                identity=identity,
                llm=self.backend,
                registry=self.registry,
                model=react_model,
                temperature=self.temperature,
                max_iterations=self.max_iterations,
                history=history,
                debug=debug,
                speech_modes=self.speech_modes,
                master_text=body,
                live_log=live,
                image_path=image_path,
            )
            dbg.mark("react_done")
            live.live(
                f"react done iters={len(loop.trace)} timeout={loop.timed_out} "
                f"tools={[s.action for s in loop.trace if s.action]}"
            )
            dbg.react_iters = len(loop.trace)
            dbg.timed_out = loop.timed_out
            for step in loop.trace:
                row = {
                    "i": step.iteration,
                    "action": step.action,
                    "thought": (step.thought or "")[:200],
                    "error": step.error,
                    "final": step.final_answer is not None,
                }
                dbg.raw_trace.append(row)
                if step.action:
                    dbg.tools.append(str(step.action))

            payload = enforce_lucy_style(_coerce_final(loop.final_answer))
            if self.critic_enabled:
                before = json.dumps(payload, ensure_ascii=False)
                payload = criticize_and_fix(
                    payload=payload,
                    user_text=body,
                    trace=loop.trace,
                    llm=self.llm,
                    identity=identity,
                )
                critic_applied = json.dumps(payload, ensure_ascii=False) != before
            dbg.mark("critic_done")
            dbg.critic_applied = critic_applied

            text_now = sanitize_speech_text(str(payload.get("text") or "").strip())
            payload["text"] = text_now
            if (
                not text_now
                or text_now.startswith("{")
                or '"emotion"' in text_now
                or loop.timed_out
            ):
                payload = self._emergency_line(body, suggested)
                critic_applied = True
                emergency = True
                payload["text"] = sanitize_speech_text(str(payload.get("text") or ""))
                dbg.note("emergency_line triggered")
            dbg.emergency = emergency

            # Anti-echo vs recent assistant lines
            recent_asst = [
                str(h.get("content") or "")
                for h in history
                if h.get("role") == "assistant"
            ][-4:]
            best_echo = 0.0
            for prev in recent_asst:
                best_echo = max(best_echo, echo_ratio(payload.get("text") or "", prev))
            dbg.echo_vs_recent = best_echo
            # Only near-verbatim echo of recent lines — no keyword filler patches
            if best_echo >= 0.85:
                dbg.note(f"echo detected ({best_echo:.2f}); one rewrite")
                try:
                    if world.get("ok") and self._world_facts_ready(world):
                        payload = self._fact_aware_rewrite(
                            ask_line,
                            world.get("prompt_block") or "",
                            suggested,
                            world=world,
                        )
                    else:
                        payload = self._emergency_line(ask_line, suggested)
                    dbg.echo_rewrite = True
                except Exception as exc:
                    dbg.errors.append(f"echo_rewrite: {exc}")
        else:
            dbg.mark("react_done")
            dbg.mark("critic_done")
            dbg.critic_applied = False
            dbg.emergency = False
            payload["text"] = sanitize_speech_text(str(payload.get("text") or "").strip())

        from ..llm.style_filter import has_kana, is_chinese_gloss

        hint_now = str(payload.get("hint") or "").strip()
        if hint_now and not is_chinese_gloss(hint_now):
            dbg.hint_source = "ja_hint_cleared" if has_kana(hint_now) else "meta_cleared"
            if has_kana(hint_now):
                dbg.note("hint was Japanese; forcing ZH gloss")
            hint_now = ""
        if is_chinese_gloss(hint_now):
            dbg.hint_source = dbg.hint_source or "model"
            payload["hint"] = hint_now
        elif str(payload.get("text") or "").strip():
            try:
                gloss = self.llm.translate_ja_to_zh_hint(payload["text"])
                if gloss and is_chinese_gloss(gloss):
                    payload["hint"] = gloss
                    dbg.hint_source = "translate"
                else:
                    payload["hint"] = ""
                    dbg.hint_source = "missing"
                    dbg.note("translate returned empty/meta/ja")
            except Exception as exc:
                payload["hint"] = ""
                dbg.hint_source = "missing"
                dbg.errors.append(f"gloss: {exc}")
        else:
            dbg.hint_source = "missing"
            payload["hint"] = ""
        dbg.mark("gloss_done")

        dbg.payload_text = str(payload.get("text") or "")
        dbg.payload_hint = str(payload.get("hint") or "")
        dbg.stage = stage  # growth snapshot for debug only; not force-injected into prompt

        if world.get("ok"):
            txt = dbg.payload_text + dbg.payload_hint
            if world.get("needs", {}).get("time") and not any(
                ch.isdigit() for ch in txt
            ):
                dbg.note("WARN: time requested but reply has no digits")
            if world.get("needs", {}).get("weather") and not any(
                k in txt
                for k in ("°", "度", "晴", "雨", "阴", "曇", "気温", "天気", "冷", "热")
            ):
                dbg.note("WARN: weather requested but reply lacks weather cues")

        return AgentResult(
            payload=payload,
            trace=(loop.trace if loop is not None else []),
            timed_out=bool(loop.timed_out) if loop is not None else False,
            critic_applied=critic_applied,
            debug=dbg.to_dict(),
        )

    @staticmethod
    def _world_facts_ready(world: dict[str, Any]) -> bool:
        """True when every host-requested world fact resolved OK."""
        needs = world.get("needs") or {}
        if (
            not needs.get("time")
            and not needs.get("weather")
            and not needs.get("stock")
        ):
            return False
        if needs.get("time") and not (world.get("time") or {}).get("ok"):
            return False
        if needs.get("weather") and not (world.get("weather") or {}).get("ok"):
            return False
        if needs.get("stock") and not (world.get("stock") or {}).get("ok"):
            return False
        return True

    def _fact_template_from_world(self, world: dict[str, Any]) -> dict[str, Any]:
        """Deterministic Lucy line from host facts — JP/ZH aligned."""
        time_info = world.get("time") or {}
        wx = world.get("weather") or {}
        stock = world.get("stock") or {}
        t_ja = str(
            time_info.get("display_ja") or time_info.get("display_zh") or ""
        ).strip()
        t_zh = str(time_info.get("display_zh") or "").strip()
        w_ja = str(wx.get("summary_ja") or "").strip()
        w_zh = str(wx.get("summary_zh") or "").strip()
        s_ja = str(stock.get("summary_ja") or "").strip()
        s_zh = str(stock.get("summary_zh") or "").strip()
        bits_ja: list[str] = []
        bits_zh: list[str] = []
        if t_ja or t_zh:
            bits_ja.append(f"今は{t_ja or t_zh}です")
            bits_zh.append(f"现在是{t_zh or t_ja}")
        if w_ja or w_zh:
            bits_ja.append(w_ja or w_zh)
            bits_zh.append(w_zh or w_ja)
        if s_ja or s_zh:
            bits_ja.append(s_ja or s_zh)
            bits_zh.append(s_zh or s_ja)
        text = (
            "マスター、" + "。".join(bits_ja) + "。"
            if bits_ja
            else "マスター、確認できました。"
        )
        hint = "；".join(bits_zh) if bits_zh else ""
        return enforce_lucy_style(
            {"emotion": "calm", "text": text, "hint": hint, "sprite_hint": None}
        )

    def _fact_aware_rewrite(
        self,
        user_text: str,
        fact_block: str,
        suggested: str | None,
        *,
        world: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Single-shot: speak prefetched time/weather/stock as Lucy (no ReAct)."""
        mode = suggested or "daily"
        messages = [
            {
                "role": "system",
                "content": (
                    "/no_think\n"
                    "你是 Lucy。用一句ですます日文直接回答 master 问的时间/天气/股价。"
                    "text（日文）与 hint（中文）必须信息对齐。"
                    "必须带上下面事实里的数字与关键词；禁止暗い夢/朝ごはん套话；禁止说没有手段。"
                    f"{fact_block}"
                    "text=日文；hint=对应中文意思（同一信息量）。"
                    '只输出：{"emotion":"calm","text":"...","hint":"..."}'
                ),
            },
            {"role": "user", "content": f"master说：{user_text}\n口调参考:{mode}"},
        ]
        raw = self.llm.chat(
            messages,
            max_tokens=280,
            temperature=0.35,
            think=False,
        )
        from .critic import _unwrap_payload

        payload = enforce_lucy_style(_unwrap_payload(parse_lucy_json(raw)))
        text = str(payload.get("text") or "").strip()
        if not text or text.startswith("{"):
            if world:
                return self._fact_template_from_world(world)
            raise ValueError(f"fact rewrite empty raw={raw[:200]!r}")
        return payload

    def _emergency_line(self, user_text: str, suggested: str | None) -> dict[str, Any]:
        """Single-shot fallback when the ReAct loop times out or returns broken JSON."""
        mode = suggested or "daily"
        mode_obs = self.registry.get_tool("speech_mode_hint")
        mode_txt = mode_obs.call({"topic": mode}) if mode_obs else mode
        mem_tool = self.registry.get_tool("search_memory")
        mem_txt = mem_tool.call({"query": user_text, "top_k": 4}) if mem_tool else ""
        messages = [
            {
                "role": "system",
                "content": (
                    "/no_think\n"
                    "扮演 Lucy。用她的性格说一句日文，不要背剧情考点。"
                    f"口调参考：{mode_txt}\n"
                    f"可选记忆：{mem_txt[:500]}\n"
                    "text=纯日文；hint=短中文。"
                    '格式：{"emotion":"...","text":"...","hint":"..."}'
                ),
            },
            {"role": "user", "content": f"master说：{user_text}"},
        ]
        old = self.llm.max_tokens
        try:
            self.llm.max_tokens = max(old, 500)
            raw = self.llm.chat(messages)
        finally:
            self.llm.max_tokens = old
        from .critic import _unwrap_payload

        return enforce_lucy_style(_unwrap_payload(parse_lucy_json(raw)))
