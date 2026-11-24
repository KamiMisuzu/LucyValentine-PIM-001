# -*- coding: utf-8 -*-
"""Event-driven personality: current traits/motives = f(past events)."""

from .author import load_author_live, merge_author_into_identity, rewrite_author_from_ledger
from .event_classifier import ClassifiedEvent, LifeEventClassifier
from .ledger import LifeEvent, PersonalityLedger, PersonalitySnapshot
from .sync import apply_personality_pull, choose_face_emotion, format_motives_block, merge_stages

__all__ = [
    "LifeEvent",
    "PersonalityLedger",
    "PersonalitySnapshot",
    "LifeEventClassifier",
    "ClassifiedEvent",
    "apply_personality_pull",
    "choose_face_emotion",
    "format_motives_block",
    "merge_stages",
    "load_author_live",
    "merge_author_into_identity",
    "rewrite_author_from_ledger",
]
