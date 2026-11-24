# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import Settings, load_settings
from .emotion.map import EmotionMapper
from .emotion.state import EmotionState
from .emotion.triggers import EmotionTriggerTable
from .face.sprite import SpriteResolver
from .agent.runner import LucyAgent
from .llm.client import LLMClient
from .llm.prompts import build_messages
from .llm.style_filter import enforce_lucy_style, parse_lucy_json
from .memory.canon import CanonMemoryStore
from .memory.personal import PersonalMemoryStore
from .memory.retrieve import retrieve_context
from .persona import format_few_shots, load_few_shots, load_persona
from .personality.author import (
    default_author_live_path,
    maybe_rewrite_after_event,
    rewrite_author_from_ledger,
)
from .personality.event_classifier import LifeEventClassifier
from .debug_turn import TurnDebugLog
from .personality.sync import apply_personality_pull, choose_face_emotion, merge_stages
from .session_history import load_recent_history
from .timeline import build_timeline, render_template
from .voice.tts_bridge import VoiceBridge


@dataclass
class TurnResult:
    user_text: str
    text: str
    hint: str
    emotion: str  # display / face / TTS channel (LLM line emotion)
    emotion_source: str
    mood: str
    bond: float
    security: float
    openness: float
    trust: float
    familiarity: float
    stage: str
    vad: dict | None
    sprite_id: str
    sprite_path: str | None
    voice_path: str | None
    voice_note: str
    memories_used: list[str]
    growth_emotion: str = "neutral"  # internal growth engine emotion (not face)
    attachment: float = 0.0
    life_event_kind: str | None = None
    event_count: int = 0
    motives_top: list[dict] | None = None
    debug: dict | None = None
    power: dict | None = None


class LucyCompanion:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or load_settings()
        s = self.settings

        self.persona = load_persona(s.path("persona"))
        self.few_shots = load_few_shots(s.path("few_shots"))
        self.canon = CanonMemoryStore(s.path("canon_memories"))
        self.personal = PersonalMemoryStore(s.path("personal_memories"))
        self.llm = LLMClient(s)
        from .power_meter import PowerMeter

        pcfg = s.power or {}
        power_path = s.project_root / str(
            pcfg.get("state_path") or "companion/data/lucy_power.json"
        )
        self.power_meter = PowerMeter(
            power_path,
            capacity=float(pcfg.get("capacity_deg", 100) or 100),
            tokens_per_full=int(pcfg.get("tokens_per_full", 100_000_000) or 100_000_000),
            enabled=bool(pcfg.get("enabled", True)),
        )
        self.llm.add_usage_hook(self.power_meter.record_tokens)
        self._agent: LucyAgent | None = None
        self.emotions = EmotionMapper(
            s.path("emotion_summary"),
            default_sprite=str(s.face.get("default_sprite", "l21")),
        )
        trigger_path = s.project_root / str(
            s.paths.get("emotion_triggers", "companion/config/emotion_triggers.json")
        )
        state_path = s.project_root / str(
            s.paths.get("emotion_state", "companion/data/emotion_state.json")
        )
        engine_cfg = s.project_root / str(
            s.paths.get("affective_engine", "companion/config/affective_engine.json")
        )
        self.emotion_state = EmotionState(
            EmotionTriggerTable(path=trigger_path),
            persist_path=state_path,
            engine_config=engine_cfg,
        )
        images_dir = s.project_root / str(s.paths.get("images_dir", "images"))
        self.sprites = SpriteResolver(images_dir)
        self.voice = VoiceBridge(
            enabled=bool(s.voice.get("enabled", False)),
            out_dir=s.project_root / str(s.voice.get("out_dir", "output/companion_voice")),
            lang=str(s.voice.get("lang", "ja")),
            project_root=s.project_root,
            python_exe=str(s.voice.get("python_exe") or "") or None,
            worker_script=str(s.voice.get("worker_script") or "") or None,
            autoplay=bool(s.voice.get("autoplay", True)),
            llm_model=str(s.llm.get("model") or "qwen3:8b"),
        )
        self.voice.set_playback_mode(str(s.voice.get("playback") or "whole"))
        chat_cfg = s.chat or {}
        recent_n = int(s.memory.get("recent_turns", 12))
        self.sessions_dir = s.path("sessions_dir")
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.history: list[dict[str, str]] = load_recent_history(
            self.sessions_dir,
            max_turns=recent_n,
            max_days=int(chat_cfg.get("history_reload_days", 7)),
        )
        self.user_address = str(chat_cfg.get("user_address_default", "master"))
        clf_state = s.project_root / str(
            s.paths.get(
                "life_event_classifier_state",
                "companion/data/life_event_classifier_state.json",
            )
        )
        self._classifier_state_path = clf_state
        self._event_classifier = LifeEventClassifier(
            cooldown_hours=float(chat_cfg.get("life_event_cooldown_hours", 6.0)),
            min_intensity=float(chat_cfg.get("life_event_min_intensity", 0.45)),
            state_path=clf_state,
        )
        self._auto_life_events = bool(chat_cfg.get("auto_life_events", True))
        self._author_live_path = default_author_live_path(s.project_root)
        alt_author = s.paths.get("author_live")
        if alt_author:
            p = Path(str(alt_author))
            self._author_live_path = p if p.is_absolute() else (s.project_root / p)
        tl = s.raw.get("timeline", {})
        self.timeline = build_timeline(
            birthday_str=str(tl.get("master_birthday", "2006-08-14")),
            restored_on=str(tl.get("restored_on") or "") or None,
        )
        agent_cfg = s.raw.get("agent") or {}
        debug_log = bool(chat_cfg.get("debug_log", True)) or bool(
            agent_cfg.get("debug_trace", False)
        )
        self.debug_log = TurnDebugLog(s.project_root, enabled=debug_log)
        self.last_debug: dict | None = None
        if bool(agent_cfg.get("enabled", True)):
            self._agent = LucyAgent(
                s,
                llm=self.llm,
                canon=self.canon,
                personal=self.personal,
                timeline=self.timeline,
                user_address=self.user_address,
            )
            self._bootstrap_personality_unity()
        self._sync_timeline_memory()

    def _bootstrap_personality_unity(self) -> None:
        """On boot: pull growth toward ledger + ensure Author live file exists."""
        if self._agent is None:
            return
        ledger = self._agent.personality_ledger
        try:
            snap = ledger.compute()
            apply_personality_pull(
                self.emotion_state.engine,
                snap.motives,
                snap.traits,
                rate=float((self.settings.chat or {}).get("personality_pull_rate", 0.18)),
            )
            self.emotion_state.engine.save()
            if not self._author_live_path.exists() and snap.event_count > 0:
                rewrite_author_from_ledger(
                    ledger,
                    live_path=self._author_live_path,
                    identity=self._agent.identity,
                )
            self._agent.refresh_identity_author(self._author_live_path)
        except Exception:
            pass

    def _sync_timeline_memory(self) -> None:
        self.personal.upsert(
            "timeline_master_age",
            render_template(
                "master birthday is {{master_birthday}}; today {{today}}; master is {{master_age}} years old; "
                "Lucy was restored by this master around {{restored_year}} when master was about {{restored_age}}.",
                self.timeline,
                address=self.user_address,
            ),
            tags=["timeline", "master_age", "auto"],
        )
        # Persist a readable growth snapshot for retrieval / debugging.
        es = self.emotion_state
        self.personal.upsert(
            "growth_snapshot",
            (
                f"Lucy relationship stage={es.stage}; "
                f"bond={es.bond:.0f}, security={es.security:.0f}, openness={es.openness:.0f}."
            ),
            tags=["growth", "auto", es.stage],
        )

    def refresh_timeline(self) -> None:
        tl = self.settings.raw.get("timeline", {})
        self.timeline = build_timeline(
            birthday_str=str(tl.get("master_birthday", "2006-08-14")),
            restored_on=str(tl.get("restored_on") or "") or None,
        )
        if self._agent is not None:
            self._agent.timeline = self.timeline
            self._agent.user_address = self.user_address
        self._sync_timeline_memory()

    def synthesize_voice(self, text: str, emotion: str = "neutral"):
        """Public TTS entry for async UI / CLI; does not block ask() by default."""
        # Keep mode in sync with settings.yaml (settings dialog may have changed it)
        self.voice.set_playback_mode(str((self.settings.voice or {}).get("playback") or "whole"))
        self.voice.enabled = bool((self.settings.voice or {}).get("enabled", True))
        return self.voice.synthesize(text, emotion)

    def synthesize_voice_stream(self, text: str, emotion: str = "neutral"):
        self.voice.set_playback_mode(str((self.settings.voice or {}).get("playback") or "whole"))
        self.voice.enabled = bool((self.settings.voice or {}).get("enabled", True))
        return self.voice.synthesize_stream(text, emotion)

    def voice_playback_mode(self) -> str:
        mode = str((self.settings.voice or {}).get("playback") or "whole").strip().lower()
        return mode if mode in {"whole", "stream"} else "whole"

    @staticmethod
    def _significant_memory_turn(
        user_text: str,
        face_emotion: str,
        *,
        life_event_kind: str | None = None,
        partner_act: str = "presence",
    ) -> bool:
        """Only keep high-signal turns in personal memory (cuts retrieval noise)."""
        if life_event_kind:
            return True
        if partner_act in {"threat", "trauma", "harsh", "soothe", "affirm"}:
            return True
        emo = (face_emotion or "").lower()
        if emo in {
            "anxious",
            "worried",
            "affection",
            "sad",
            "pleading",
            "angry",
            "joyful",
        }:
            return True
        # Keep narrow — broad words like 回家 flooded personal store with chitchat
        markers = (
            "永远",
            "丢掉",
            "不要我",
            "生日",
            "爱你",
            "离开我",
            "对不起",
            "谢谢",
            "一起",
        )
        return any(m in (user_text or "") for m in markers)

    def _unified_growth_snapshot(self) -> dict:
        from .emotion.stages import STAGE_BLURBS

        es = self.emotion_state
        ledger_stage = es.stage
        pers: dict = {}
        if self._agent is not None:
            try:
                pers = self._agent.personality_ledger.snapshot_for_growth()
                ledger_stage = str(pers.get("stage") or pers.get("stage_hint") or es.stage)
                apply_personality_pull(
                    es.engine,
                    dict(pers.get("motives") or {}),
                    dict(pers.get("traits") or {}),
                    rate=float((self.settings.chat or {}).get("personality_pull_rate", 0.10)),
                )
            except Exception:
                pers = {}
        stage = merge_stages(es.stage, ledger_stage)
        return {
            "stage": stage,
            "growth_stage": es.stage,
            "ledger_stage": ledger_stage,
            "bond": es.bond,
            "security": es.security,
            "openness": es.openness,
            "trust": getattr(es, "trust", es.engine.dims.get("trust", 0) * 100),
            "familiarity": getattr(
                es, "familiarity", es.engine.dims.get("familiarity", 0) * 100
            ),
            "attachment": float(getattr(es, "attachment", 0.2) or 0.2),
            "blurb": STAGE_BLURBS.get(stage, STAGE_BLURBS.get(es.stage, "")),
            "personality_from_events": pers,
        }

    def ask(
        self,
        user_text: str,
        *,
        with_voice: bool = False,
        image_path: str | None = None,
    ) -> TurnResult:
        self.refresh_timeline()
        mem_cfg = self.settings.memory
        recent_n = int(mem_cfg.get("recent_turns", 12))
        history = self.history[-(recent_n * 2) :]

        memories_used: list[str] = []
        turn_debug: dict = {}
        if self._agent is not None:
            self._agent.refresh_identity_author(self._author_live_path)
            self._agent.set_growth_snapshot(self._unified_growth_snapshot())
            agent_out = self._agent.ask(
                user_text, history=history, image_path=image_path
            )
            payload = agent_out.payload
            turn_debug = dict(agent_out.debug or {})
            for step in agent_out.trace:
                if step.action and step.observation:
                    memories_used.append(f"{step.action}:{step.iteration}")
        else:
            from .vision import multimodal_user_content

            bundle = retrieve_context(
                user_text,
                self.canon,
                self.personal,
                canon_top_k=int(mem_cfg.get("canon_top_k", 6)),
                personal_top_k=int(mem_cfg.get("personal_top_k", 4)),
            )
            for card in bundle.canon + bundle.personal:
                card.text = render_template(card.text, self.timeline, address=self.user_address)
            emotion_hint = self.emotion_state.prompt_hint(user_text)
            messages = build_messages(
                persona=self.persona,
                few_shot_block=format_few_shots(self.few_shots),
                memory=bundle,
                history=history,
                user_text=user_text,
                user_address=self.user_address,
                timeline=self.timeline,
                emotion_hint=emotion_hint,
            )
            if image_path and messages:
                messages[-1] = {
                    **messages[-1],
                    "content": multimodal_user_content(
                        str(messages[-1].get("content") or user_text),
                        image_path,
                    ),
                }
            raw = self.llm.chat(messages)
            if self.settings.llm.get("rewrite_enabled", True):
                persona_for_rewrite = render_template(
                    self.persona, self.timeline, address=self.user_address
                )
                raw = self.llm.rewrite_as_lucy(raw, persona_for_rewrite)
            from .llm.style_filter import is_chinese_gloss, is_meta_hint, sanitize_speech_text

            payload = enforce_lucy_style(parse_lucy_json(raw))
            payload["text"] = sanitize_speech_text(str(payload.get("text") or ""))
            hint_now = str(payload.get("hint") or "").strip()
            if (not is_chinese_gloss(hint_now)) and payload["text"]:
                try:
                    gloss = self.llm.translate_ja_to_zh_hint(payload["text"])
                    payload["hint"] = gloss if is_chinese_gloss(gloss) and not is_meta_hint(gloss) else ""
                except Exception:
                    payload["hint"] = ""
            memories_used = [c.id for c in bundle.canon + bundle.personal]

        llm_emotion = str(payload.get("emotion") or "neutral")
        decision = self.emotion_state.finalize(user_text, llm_emotion)
        growth_emotion = str(decision.emotion or "neutral")
        attachment = float(
            getattr(decision, "attachment", getattr(self.emotion_state, "attachment", 0.0))
            or 0.0
        )
        face_emotion, face_src = choose_face_emotion(
            llm_emotion=getattr(decision, "llm_suggested", None) or llm_emotion,
            growth_emotion=growth_emotion,
            attachment=attachment,
            prefer_llm=bool(self.settings.face.get("prefer_llm_sprite", True)),
            blend_on_activation=bool(self.settings.face.get("blend_growth_on_activation", True)),
        )
        face_emotion = str(face_emotion or "neutral")

        # Auto life-event from significant turns → ledger grows without tool lottery
        life_kind: str | None = None
        if self._auto_life_events and self._agent is not None:
            classified = self._event_classifier.classify(
                user_text,
                face_emotion=face_emotion,
                growth_emotion=growth_emotion,
                partner_act=str(getattr(decision, "partner_act", "presence") or "presence"),
                attachment=attachment,
                lucy_text=str(payload.get("text") or ""),
            )
            if classified is not None:
                try:
                    ev = self._agent.personality_ledger.append(
                        {
                            "kind": classified.kind,
                            "summary": classified.summary,
                            "intensity": classified.intensity,
                            "author_note": classified.author_note,
                            "source": "auto",
                            "tags": ["auto", classified.reason],
                        },
                        persist=True,
                    )
                    life_kind = ev.kind
                    memories_used.append(f"auto_life_event:{ev.kind}")
                    maybe_rewrite_after_event(
                        self._agent.personality_ledger,
                        ev,
                        live_path=self._author_live_path,
                        identity=self._agent.identity,
                    )
                    self._agent.refresh_identity_author(self._author_live_path)
                    # Soft re-pull so dims track the new event this turn
                    snap = self._agent.personality_ledger.compute()
                    apply_personality_pull(
                        self.emotion_state.engine,
                        snap.motives,
                        snap.traits,
                        rate=0.14,
                    )
                    self.emotion_state.engine.save()
                    self._event_classifier.save_state()
                except Exception:
                    life_kind = None

        # Unified stage for session display after possible ledger update
        event_count = 0
        motives_top: list[dict] | None = None
        ledger_stage = decision.stage
        if self._agent is not None:
            try:
                pers = self._agent.personality_ledger.snapshot_for_growth()
                ledger_stage = str(pers.get("stage") or decision.stage)
                event_count = int(pers.get("event_count") or 0)
                motives_top = list(pers.get("motives_ranked") or [])[:4]
            except Exception:
                pass
        unified_stage = merge_stages(decision.stage, ledger_stage)

        sprite_id = self.emotions.sprite_for(
            face_emotion, hint=payload.get("sprite_hint")
        )
        sprite = self.sprites.resolve(sprite_id, face_emotion)

        voice_path = None
        voice_note = "voice deferred (async)"
        if with_voice:
            voice = self.voice.synthesize(payload["text"], face_emotion)
            voice_path = str(voice.out_path) if voice.out_path else None
            voice_note = voice.note
        elif not self.voice.enabled:
            voice_note = "voice disabled"

        hist_user = user_text
        if image_path:
            hist_user = (user_text.strip() + "\n（附图）").strip() or "（附图）"
        self.history.append({"role": "user", "content": hist_user})
        self.history.append({"role": "assistant", "content": payload["text"]})

        hint = str(payload.get("hint") or "").strip()
        partner_act = str(getattr(decision, "partner_act", "presence") or "presence")
        save_each = bool(self.settings.chat.get("save_personal_memory_each_turn", False))
        if save_each or self._significant_memory_turn(
            user_text,
            face_emotion,
            life_event_kind=life_kind,
            partner_act=partner_act,
        ):
            mem_line = (
                f"master said: {user_text} | Lucy replied ({face_emotion}): {payload['text']}"
            )
            if hint:
                mem_line += f" / hint: {hint}"
            tags = ["dialog", face_emotion, decision.source, partner_act]
            if life_kind:
                tags.append(f"life:{life_kind}")
            self.personal.append(mem_line, tags=tags)

        # Keep growth_snapshot personal card in sync with unified stage
        try:
            self.personal.upsert(
                "growth_snapshot",
                (
                    f"Lucy relationship stage={unified_stage}; "
                    f"bond={decision.bond:.0f}, security={decision.security:.0f}, "
                    f"openness={decision.openness:.0f}; events={event_count}."
                ),
                tags=["growth", "auto", unified_stage],
            )
        except Exception:
            pass

        result = TurnResult(
            user_text=user_text,
            text=payload["text"],
            hint=hint,
            emotion=face_emotion,
            emotion_source=f"{decision.source}|face:{face_src}",
            mood=decision.mood,
            bond=decision.bond,
            security=decision.security,
            openness=decision.openness,
            trust=getattr(decision, "trust", 0.0),
            familiarity=getattr(decision, "familiarity", 0.0),
            stage=unified_stage,
            vad=getattr(decision, "vad", None),
            sprite_id=sprite.sprite_id,
            sprite_path=str(sprite.path) if sprite.path else None,
            voice_path=voice_path,
            voice_note=voice_note,
            memories_used=memories_used,
            growth_emotion=growth_emotion,
            attachment=attachment,
            life_event_kind=life_kind,
            event_count=event_count,
            motives_top=motives_top,
            debug=None,
            power=self.power_meter.snapshot().as_dict(),
        )
        # Finalize debug dump for this turn
        turn_debug["life_event"] = life_kind
        turn_debug["stage"] = unified_stage
        turn_debug["memories_used"] = list(memories_used)
        turn_debug["face_emotion"] = face_emotion
        turn_debug["growth_emotion"] = growth_emotion
        turn_debug["attachment"] = attachment
        turn_debug["text"] = result.text
        turn_debug["hint"] = result.hint
        turn_debug["power"] = result.power
        result.debug = turn_debug
        self.last_debug = turn_debug
        try:
            path = self.debug_log.write_dict(turn_debug)
            if path and bool((self.settings.chat or {}).get("debug_print", True)):
                ph = turn_debug.get("phases_ms") or {}
                print(
                    f"[LucyDebug] iters={turn_debug.get('react_iters')} "
                    f"tools={turn_debug.get('tools')} "
                    f"echo={turn_debug.get('echo_vs_recent')} "
                    f"hint={turn_debug.get('hint_source')} "
                    f"react_ms={ph.get('react_ms')} gloss_ms={ph.get('gloss_ms')} "
                    f"prefetch={turn_debug.get('prefetch')} "
                    f"log={path}",
                    flush=True,
                )
                for n in turn_debug.get("notes") or []:
                    print(f"[LucyDebug] note: {n}", flush=True)
                for e in turn_debug.get("errors") or []:
                    print(f"[LucyDebug] ERROR: {e}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[LucyDebug] log write failed: {exc}", flush=True)
        self._log_turn(result)
        return result

    def status(self) -> dict:
        """Compact runtime snapshot for CLI /status and v1 harness."""
        es = self.emotion_state
        out: dict = {
            "stage": es.stage,
            "bond": round(es.bond, 1),
            "security": round(es.security, 1),
            "openness": round(es.openness, 1),
            "attachment": round(float(es.attachment), 3),
            "history_msgs": len(self.history),
            "auto_life_events": self._auto_life_events,
        }
        if self._agent is not None:
            try:
                pers = self._agent.personality_ledger.snapshot_for_growth()
                out["unified_stage"] = merge_stages(
                    es.stage, str(pers.get("stage") or es.stage)
                )
                out["ledger_stage"] = pers.get("stage")
                out["event_count"] = pers.get("event_count")
                out["motives_top"] = (pers.get("motives_ranked") or [])[:5]
                out["traits"] = {
                    k: round(float(v), 3)
                    for k, v in dict(pers.get("traits") or {}).items()
                    if k
                    in {
                        "abandonment_sensitivity",
                        "soft_cheer",
                        "neuroticism",
                        "agreeableness",
                    }
                }
                author = dict(self._agent.identity.get("L3_author") or {})
                out["self_story"] = str(author.get("self_story") or "")[:180]
            except Exception as exc:
                out["ledger_error"] = str(exc)
        return out

    def _log_turn(self, result: TurnResult) -> None:
        day = time.strftime("%Y%m%d")
        path = self.sessions_dir / f"session_{day}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")

    def attach_voice_to_last_turn(
        self,
        voice_path: str | Path,
        *,
        user_text: str | None = None,
        text: str | None = None,
    ) -> bool:
        """Patch newest matching session row with wav path (desktop TTS is async)."""
        vp = Path(voice_path)
        if not vp.exists():
            return False
        try:
            stored = str(vp.resolve().relative_to(self.settings.project_root.resolve()))
        except Exception:
            stored = str(vp.resolve())

        want_user = (user_text or "").strip()
        want_ja = (text or "").strip()
        files = sorted(self.sessions_dir.glob("session_*.jsonl"), reverse=True)[:3]
        for path in files:
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            changed = False
            for i in range(len(lines) - 1, -1, -1):
                line = lines[i].strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(raw, dict):
                    continue
                ja = str(raw.get("text") or "").strip()
                user = str(raw.get("user_text") or "").strip()
                if want_ja and ja != want_ja:
                    continue
                if want_user and user != want_user:
                    continue
                if not ja and not str(raw.get("hint") or "").strip():
                    continue
                raw["voice_path"] = stored
                raw["voice_note"] = f"saved {vp.name}"
                lines[i] = json.dumps(raw, ensure_ascii=False)
                changed = True
                break
            if changed:
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return True
        return False
