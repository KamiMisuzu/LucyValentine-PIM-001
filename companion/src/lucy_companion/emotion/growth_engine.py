# -*- coding: utf-8 -*-
"""
Dyadic attachment growth for Lucy (human-like, not game XP).

Grounded in:
- Adult attachment / felt security (Mikulincer & Shaver)
- Temporal interpersonal emotion systems (Butler TIES)
- Co-regulation vs co-dysregulation (Reed, Barnard, Butler)

Loop: threat → attachment activation → proximity seeking →
      partner response → co-regulate / co-dysregulate → felt security (slow)
"""
from __future__ import annotations

import json
import math
import random
import time
from dataclasses import dataclass
from pathlib import Path

from .ou import ou_step
from .stages import STAGE_BLURBS, resolve_stage
from .triggers import EmotionTriggerTable, TriggerHit
from .vad import PROTOTYPES, VAD, blend_toward, nearest_emotion


@dataclass
class GrowthDecision:
    emotion: str
    source: str
    trigger: str | None
    mood: str
    stage: str
    bond: float
    security: float
    openness: float
    trust: float
    familiarity: float
    vad: dict[str, float]
    llm_suggested: str | None = None
    hours_since_last: float = 0.0
    habituation: float = 1.0
    attachment: float = 0.0
    coregulation: str = "neutral"
    partner_act: str = "presence"


class GrowthEngine:
    def __init__(
        self,
        config_path: Path,
        triggers: EmotionTriggerTable,
        persist_path: Path | None = None,
        seed: int | None = None,
    ):
        self.config_path = config_path
        self.triggers = triggers
        self.persist_path = persist_path
        self.rng = random.Random(seed)
        self.cfg = json.loads(config_path.read_text(encoding="utf-8"))

        rel = self.cfg.get("relation", {})
        dims = dict(rel.get("dims") or {})
        self.dims = {
            "bond": float(dims.get("bond", 0.35)),
            "security": float(dims.get("security", 0.28)),
            "openness": float(dims.get("openness", 0.22)),
            "trust": float(dims.get("trust", 0.30)),
            "familiarity": float(dims.get("familiarity", 0.20)),
        }
        vad0 = dict((self.cfg.get("vad") or {}).get("baseline") or {})
        self.vad = VAD.from_dict(vad0)
        att = self.cfg.get("attachment") or {}
        self.attachment = float(att.get("start_activation", 0.12))
        self.stage = "fragile_new"
        self.last_emotion = "neutral"
        self.last_trigger: str | None = None
        self.last_coregulation = "neutral"
        self.last_partner_act = "presence"
        self.last_unix = time.time()
        self.first_unix = self.last_unix
        self.turns = 0
        self.event_last_unix: dict[str, float] = {}
        if persist_path and persist_path.exists():
            self.load()
        self._refresh_stage()

    def on_session_start(self) -> None:
        now = time.time()
        hours = max(0.0, (now - self.last_unix) / 3600.0)
        self._apply_time(hours)
        self.last_unix = now
        self.save()

    def observe_and_decide(self, user_text: str, llm_emotion: str | None) -> GrowthDecision:
        now = time.time()
        hours = max(0.0, (now - self.last_unix) / 3600.0)
        if hours > 0.05:
            self._apply_time(min(hours, float(self.cfg.get("ou", {}).get("dt_hours_cap", 96))))

        hit = self.triggers.match(user_text)
        event_name = self._event_from_hit(hit, user_text)
        partner_act = self._classify_partner_act(event_name)
        hab = self._habituation(event_name, now)
        activated_before = self.attachment >= 0.28

        # 1) relational deltas from the event (small, habituated)
        self._apply_event(event_name, hab)

        # 2) attachment activation from partner act
        self._update_attachment(partner_act, hab)

        # 3) dyadic co-regulation / co-dysregulation
        coreg = self._apply_coregulation(partner_act, hab, activated_before=activated_before)

        # 4) momentary affect from trigger + LLM (soft, not hard lock)
        source = "vad"
        pace = self.cfg.get("pace") or {}
        if hit:
            blend_max = float(pace.get("vad_trigger_blend_max", 0.16))
            weight = min(blend_max, max(0.04, hit.weight * 0.18 * hab))
            # attachment threats must actually move felt affect (not stay near-neutral)
            if partner_act in {"threat", "trauma", "harsh"}:
                amp = 1.0 + float(
                    (self.cfg.get("coregulation") or {}).get(
                        "activation_amplifies_threat_vad", 0.75
                    )
                ) * max(self.attachment, 0.4)
                weight = min(0.55, max(0.28, weight * amp))
            self.vad = blend_toward(hit.emotion, weight, self.vad)
            source = f"event:{event_name}"

        llm_emotion = (llm_emotion or "").lower().strip() or None
        if llm_emotion:
            pull = float(pace.get("vad_llm_pull", 0.18))
            # high activation: don't let a cheerful LLM suggestion wipe fear instantly
            if self.attachment >= 0.45 and llm_emotion in {"joyful", "happy"}:
                pull *= 0.35
            self.vad = blend_toward(llm_emotion, pull, self.vad)
            source = f"{source}+llm"

        # 5) proximity-seeking bias while attachment system is on
        self._apply_proximity_bias()

        emotion = self._resolve_emotion()
        self.turns += 1
        self.last_emotion = emotion
        self.last_trigger = hit.name if hit else None
        self.last_coregulation = coreg
        self.last_partner_act = partner_act
        self.last_unix = now
        self.event_last_unix[event_name] = now
        self._refresh_stage()
        self.save()

        return GrowthDecision(
            emotion=emotion,
            source=source,
            trigger=hit.name if hit else None,
            mood=emotion,
            stage=self.stage,
            bond=self.dims["bond"] * 100.0,
            security=self.dims["security"] * 100.0,
            openness=self.dims["openness"] * 100.0,
            trust=self.dims["trust"] * 100.0,
            familiarity=self.dims["familiarity"] * 100.0,
            vad=self.vad.as_dict(),
            llm_suggested=llm_emotion,
            hours_since_last=hours,
            habituation=hab,
            attachment=self.attachment,
            coregulation=coreg,
            partner_act=partner_act,
        )

    def prompt_hint(self, user_text: str) -> str:
        hit = self.triggers.match(user_text)
        blurb = STAGE_BLURBS.get(self.stage, "")
        act = self._classify_partner_act(self._event_from_hit(hit, user_text))
        lines = [
            f"相处感觉：{self.stage} — {blurb}",
            (
                f"慢变量（不要报数）：亲近感 / 安心感(felt security) / 信任 "
                f"大致在 {self.dims['bond']:.2f} / {self.dims['security']:.2f} / {self.dims['trust']:.2f}"
            ),
            "像真人双向情感：威胁会唤醒依恋；master 安抚则共调节回稳，冷硬则共失调放大；安心感要靠长时间回应慢慢攒。",
            "不要每句宣布‘我更信任你了’；用细微语气、靠近或退缩就好。",
        ]
        if self.attachment >= 0.35:
            lines.append(
                f"此刻依恋被激活（约 {self.attachment:.2f}）：会想确认 master 还在、自己还有用；语气可更小心、更靠近。"
            )
        if act == "soothe" and self.attachment >= 0.25:
            lines.append("master 在安抚：让身体慢慢松下来，不要瞬间变成开心过头。")
        elif act in {"threat", "trauma"}:
            lines.append("这句话像威胁/旧伤：先慌、想抓住对方，不要立刻理智分析。")
        elif act == "harsh":
            lines.append("master 语气硬：更容易共失调，委屈和害怕会叠在一起。")
        if hit:
            lines.append(f"这一句触到了：{hit.name}")
        return "\n".join(lines)

    # --- classification -------------------------------------------------

    def _event_classes(self) -> dict[str, list[str]]:
        return dict(self.cfg.get("event_class") or {})

    def _event_from_hit(self, hit: TriggerHit | None, user_text: str) -> str:
        if hit:
            if hit.growth in {"praise", "care", "comfort"}:
                return hit.growth
            if hit.name in (self.cfg.get("event_deltas") or {}):
                return hit.name
            return hit.name
        return "presence"

    def _classify_partner_act(self, event_name: str) -> str:
        classes = self._event_classes()
        for label, names in classes.items():
            if event_name in names:
                if label == "available":
                    return "presence" if event_name == "presence" else "available"
                return label
        if event_name == "anger_at_lucy":
            return "harsh"
        if event_name in {"abandon_fear"}:
            return "threat"
        if event_name in {"comfort", "apology_to_lucy"}:
            return "soothe"
        if event_name in {"praise", "remember_eternity", "restore_gratitude", "birthday"}:
            return "affirm"
        if event_name in {"care", "sick_care"}:
            return "care"
        if event_name == "presence":
            return "presence"
        return "presence"

    # --- dynamics -------------------------------------------------------

    def _habituation(self, event_name: str, now: float) -> float:
        """Same stimulus soon again hits weaker — human sensory/affective adaptation."""
        pace = self.cfg.get("pace") or {}
        half = float(pace.get("habituation_half_life_hours", 5.0))
        floor = float(pace.get("habituation_floor", 0.18))
        last = float(self.event_last_unix.get(event_name, 0.0))
        if last <= 0 or event_name == "presence":
            return 1.0
        dt_h = max(0.0, (now - last) / 3600.0)
        strength = 1.0 - (1.0 - floor) * math.exp(-0.693147 * dt_h / max(1e-6, half))
        return max(floor, min(1.0, strength))

    def _apply_event(self, event_name: str, hab: float) -> None:
        deltas = (self.cfg.get("event_deltas") or {}).get(event_name) or {}
        if not deltas:
            return
        pace = self.cfg.get("pace") or {}
        rel_scale = float(pace.get("relation_scale", 0.32)) * hab
        vad_scale = float(pace.get("vad_event_scale", 0.38)) * hab

        for key in self.dims:
            if key in deltas:
                self.dims[key] = self._clamp01(
                    self.dims[key] + float(deltas[key]) * rel_scale
                )

        vad_delta = deltas.get("vad") or {}
        if vad_delta:
            self.vad = self.vad.bump(
                dv=float(vad_delta.get("v", 0.0)) * vad_scale,
                da=float(vad_delta.get("a", 0.0)) * vad_scale,
                dd=float(vad_delta.get("d", 0.0)) * vad_scale,
            )

    def _update_attachment(self, partner_act: str, hab: float) -> None:
        att = self.cfg.get("attachment") or {}
        if partner_act == "threat":
            gain = float(att.get("threat_gain", 0.55)) * hab
            self.attachment = self._clamp01(self.attachment + gain)
        elif partner_act == "trauma":
            gain = float(att.get("mild_threat_gain", 0.28)) * hab
            self.attachment = self._clamp01(self.attachment + gain)
        elif partner_act == "harsh":
            gain = float(att.get("harsh_spike", 0.18)) * hab
            self.attachment = self._clamp01(self.attachment + gain)
        elif partner_act == "soothe":
            relief = float(att.get("soothe_relief", 0.22)) * hab
            # soothing works better when she already trusts a little
            relief *= 0.7 + 0.6 * self.dims["security"]
            self.attachment = self._clamp01(self.attachment - relief)
        elif partner_act in {"affirm", "care", "available", "presence"}:
            relief = float(att.get("presence_relief", 0.06)) * hab
            if partner_act == "affirm":
                relief *= 1.4
            self.attachment = self._clamp01(self.attachment - relief)

    def _apply_coregulation(
        self, partner_act: str, hab: float, *, activated_before: bool
    ) -> str:
        """
        Reed et al.: when one partner is dysregulated, the other can pull toward
        or away from a shared steady state.
        First threat only activates; stacking threat/harsh while already up = co-dysregulate.
        """
        cg = self.cfg.get("coregulation") or {}
        activated_now = self.attachment >= 0.28

        if activated_now and partner_act == "soothe":
            self._apply_named_delta(
                cg.get("soothe_while_activated") or {},
                hab * (0.6 + 0.4 * self.attachment),
            )
            pull = float(cg.get("calm_partner_pull", 0.08)) * hab
            self.vad = blend_toward("shy", pull * 0.5, self.vad)
            self.vad = blend_toward("affection", pull * 0.5, self.vad)
            return "co_regulate"

        if partner_act in {"threat", "harsh"} and activated_before:
            self._apply_named_delta(
                cg.get("harsh_while_activated") or {},
                hab * (0.5 + 0.5 * self.attachment),
            )
            return "co_dysregulate"

        if partner_act in {"threat", "trauma", "harsh"}:
            return "activated"

        if activated_now and partner_act in {"presence", "available", "care", "affirm"}:
            self._apply_named_delta(
                cg.get("presence_while_activated") or {},
                hab * (0.5 + 0.5 * self.attachment),
            )
            return "co_regulate_soft"

        if partner_act == "soothe":
            return "soothe"
        return "neutral"

    def _apply_named_delta(self, block: dict, scale: float) -> None:
        if not block:
            return
        for key in self.dims:
            if key in block:
                self.dims[key] = self._clamp01(
                    self.dims[key] + float(block[key]) * scale
                )
        vad_delta = block.get("vad") or {}
        if vad_delta:
            self.vad = self.vad.bump(
                dv=float(vad_delta.get("v", 0.0)) * scale,
                da=float(vad_delta.get("a", 0.0)) * scale,
                dd=float(vad_delta.get("d", 0.0)) * scale,
            )

    def _apply_proximity_bias(self) -> None:
        att_cfg = self.cfg.get("attachment") or {}
        threshold = float(att_cfg.get("proximity_bias_at", 0.35))
        if self.attachment < threshold:
            return
        strength = (self.attachment - threshold) / max(1e-6, 1.0 - threshold)
        weight = 0.12 + 0.28 * strength
        if self.dims["security"] < 0.35:
            target = "pleading"
        elif self.attachment > 0.65:
            target = "anxious"
        else:
            target = "worried"
        self.vad = blend_toward(target, weight, self.vad)

    def _resolve_emotion(self) -> str:
        """When attachment is hot, never read as blank-neutral — she is seeking proximity."""
        emo = nearest_emotion(self.vad)
        att_cfg = self.cfg.get("attachment") or {}
        prox = list(att_cfg.get("proximity_emotions") or ["worried", "anxious", "pleading", "shy"])
        if self.attachment < 0.40:
            return emo
        if emo in prox or emo in {"sad", "serious"}:
            return emo
        # stuck near neutral/happy while activated → pick nearest proximity prototype
        best = prox[0]
        best_dist = 1e9
        for name in prox:
            proto = PROTOTYPES[name]
            dist = (
                (self.vad.v - proto.v) ** 2
                + (self.vad.a - proto.a) ** 2
                + (self.vad.d - proto.d) ** 2
            )
            if dist < best_dist:
                best_dist = dist
                best = name
        return best

    def _security_shifted_baseline(self) -> dict[str, float]:
        base = dict((self.cfg.get("vad") or {}).get("baseline") or {})
        shift = dict((self.cfg.get("vad") or {}).get("security_baseline_shift") or {})
        s = self.dims["security"]
        return {
            "v": float(base.get("v", 0.12)) + float(shift.get("v_per_security", 0.0)) * (s - 0.3),
            "a": float(base.get("a", 0.26)) + float(shift.get("a_per_security", 0.0)) * (s - 0.3),
            "d": float(base.get("d", 0.34)) + float(shift.get("d_per_security", 0.0)) * (s - 0.3),
        }

    def _apply_time(self, hours: float) -> None:
        if hours <= 0:
            return
        hours = min(hours, float(self.cfg.get("ou", {}).get("dt_hours_cap", 96)))
        ou_cfg = self.cfg.get("ou", {})
        theta = float(ou_cfg.get("theta", 0.45))
        sigma = float(ou_cfg.get("sigma", 0.028))
        baseline = self._security_shifted_baseline()
        self.vad = VAD(
            v=ou_step(self.vad.v, baseline["v"], hours, theta, sigma, self.rng),
            a=ou_step(self.vad.a, baseline["a"], hours, theta, sigma * 0.8, self.rng),
            d=ou_step(self.vad.d, baseline["d"], hours, theta, sigma * 0.8, self.rng),
        ).clamp()

        # attachment activation decays over hours (felt threat fades if nothing new)
        att = self.cfg.get("attachment") or {}
        half = float(att.get("decay_half_life_hours", 3.5))
        decay = math.exp(-0.693147 * hours / max(1e-6, half))
        self.attachment = self._clamp01(self.attachment * decay)

        days = hours / 24.0
        decay_rates = dict((self.cfg.get("relation") or {}).get("passive_decay_per_day") or {})
        for key, rate in decay_rates.items():
            if key in self.dims:
                self.dims[key] = self._clamp01(self.dims[key] - float(rate) * days)

        absence = self.cfg.get("absence") or {}
        if hours >= float(absence.get("miss_after_hours", 48)):
            hit = float(absence.get("security_hit_per_day", 0.0022)) * days
            self.dims["security"] = self._clamp01(self.dims["security"] - hit)
            rise = float(absence.get("activation_rise_per_day", 0.04)) * days
            self.attachment = self._clamp01(self.attachment + rise)
            lonely = absence.get("loneliness_vad") or {}
            scale = min(1.0, days / 3.0)
            self.vad = self.vad.bump(
                dv=float(lonely.get("v", 0.0)) * scale,
                da=float(lonely.get("a", 0.0)) * scale,
                dd=float(lonely.get("d", 0.0)) * scale,
            )
        self._refresh_stage()

    def _refresh_stage(self) -> None:
        rules = list((self.cfg.get("relation") or {}).get("stages") or [])
        self.stage = resolve_stage(self.dims, rules)

    @staticmethod
    def _clamp01(x: float) -> float:
        return max(0.0, min(1.0, float(x)))

    def save(self) -> None:
        if not self.persist_path:
            return
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "engine": "dyadic_attachment_v1",
            "dims": self.dims,
            "vad": self.vad.as_dict(),
            "attachment": self.attachment,
            "stage": self.stage,
            "last_emotion": self.last_emotion,
            "last_trigger": self.last_trigger,
            "last_coregulation": self.last_coregulation,
            "last_partner_act": self.last_partner_act,
            "last_unix": self.last_unix,
            "first_unix": self.first_unix,
            "turns": self.turns,
            "event_last_unix": self.event_last_unix,
        }
        self.persist_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def load(self) -> None:
        raw = json.loads(self.persist_path.read_text(encoding="utf-8"))
        if "dims" in raw:
            self.dims.update({k: float(v) for k, v in dict(raw["dims"]).items() if k in self.dims})
        else:
            for k in ("bond", "security", "openness"):
                if k in raw:
                    val = float(raw[k])
                    self.dims[k] = self._clamp01(val / 100.0 if val > 1.5 else val)
            self.dims["trust"] = self._clamp01(
                float(raw.get("trust", (self.dims["bond"] + self.dims["security"]) / 2.0))
            )
        if "vad" in raw:
            self.vad = VAD.from_dict(raw["vad"])
        if "attachment" in raw:
            self.attachment = self._clamp01(float(raw["attachment"]))
        self.stage = str(raw.get("stage", self.stage))
        self.last_emotion = str(raw.get("last_emotion", self.last_emotion))
        self.last_trigger = raw.get("last_trigger")
        self.last_coregulation = str(raw.get("last_coregulation", self.last_coregulation))
        self.last_partner_act = str(raw.get("last_partner_act", self.last_partner_act))
        self.last_unix = float(raw.get("last_unix", time.time()))
        self.first_unix = float(raw.get("first_unix", self.last_unix))
        self.turns = int(raw.get("turns", 0))
        self.event_last_unix = {
            str(k): float(v) for k, v in dict(raw.get("event_last_unix") or {}).items()
        }
