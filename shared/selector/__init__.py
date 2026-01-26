"""Smart Selector - Determines which visual elements should receive ALT text."""

from .selector import run_selector
from .types import (
    SelectorDecision,
    ContentScope,
    EscalationStrategy,
    SelectorManifestRecord,
    SelectorManifest,
)

__all__ = [
    "run_selector",
    "SelectorDecision",
    "ContentScope",
    "EscalationStrategy",
    "SelectorManifestRecord",
    "SelectorManifest",
]
