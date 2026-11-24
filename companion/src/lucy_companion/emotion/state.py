# -*- coding: utf-8 -*-
"""Compatibility facade: EmotionState -> dyadic GrowthEngine."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .growth_engine import GrowthEngine
from .triggers import EmotionTriggerTable


@dataclass
class EmotionDecision:
    emotion: str
    source: str
    trigger: str | None
    mood: str
    inertia_left: int
    bond: float
    security: float
    openness: float
    stage: str
    trust: float = 0.0
    familiarity: float = 0.0
    vad: dict | None = None
    llm_suggested: str | None = None
    habituation: float = 1.0
    attachment: float = 0.0
    coregulation: str = "neutral"
    partner_act: str = "presence"


class EmotionState:
    """
    Long-term growth runtime facade used by pipeline.
    Keeps old method names while backing onto GrowthEngine.
    """

    def __init__(
        self,
        table: EmotionTriggerTable,
        persist_path: Path | None = None,
        engine_config: Path | None = None,
    ):
        if engine_config is None:
            engine_config = Path(
                r"G:\LIngyuanli\Project\Lucy\companion\config\affective_engine.json"
            )
        self.engine = GrowthEngine(
            config_path=engine_config,
            triggers=table,
            persist_path=persist_path,
        )
        self.engine.on_session_start()

    @property
    def mood(self) -> str:
        return self.engine.last_emotion

    @property
    def stage(self) -> str:
        return self.engine.stage

    @property
    def bond(self) -> float:
        return self.engine.dims["bond"] * 100.0

    @property
    def security(self) -> float:
        return self.engine.dims["security"] * 100.0

    @property
    def openness(self) -> float:
        return self.engine.dims["openness"] * 100.0

    @property
    def attachment(self) -> float:
        return self.engine.attachment

    def prompt_hint(self, user_text: str) -> str:
        return self.engine.prompt_hint(user_text)

    def finalize(self, user_text: str, llm_emotion: str | None) -> EmotionDecision:
        d = self.engine.observe_and_decide(user_text, llm_emotion)
        return EmotionDecision(
            emotion=d.emotion,
            source=d.source,
            trigger=d.trigger,
            mood=d.mood,
            inertia_left=0,
            bond=d.bond,
            security=d.security,
            openness=d.openness,
            stage=d.stage,
            trust=d.trust,
            familiarity=d.familiarity,
            vad=d.vad,
            llm_suggested=d.llm_suggested,
            habituation=d.habituation,
            attachment=d.attachment,
            coregulation=d.coregulation,
            partner_act=d.partner_act,
        )
