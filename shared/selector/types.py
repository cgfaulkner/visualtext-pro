"""Type definitions for Smart Selector."""

from typing import Dict, List, Literal, TypedDict, Any

# Enum-like types using Literal
SelectorDecision = Literal[
    "include_atomic",
    "include_group",
    "exclude_decorative",
    "exclude_redundant",
    "escalate_manual_review",
    "preserve_conflict",
]

ContentScope = Literal["image", "group", "slide_context"]

EscalationStrategy = Literal[
    "none",
    "include_with_ambiguous_reason",
    "defer_to_manual_review",
    "render_and_assist",
    "convert_and_reinspect",
]


class SelectorManifestRecord(TypedDict):
    """A single selector decision record matching Section 5 v1.0 normative shape."""

    selector_version: str
    element_id: str
    parent_group_id: str | None
    selector_decision: SelectorDecision
    content_scope: ContentScope
    reason_code: str
    human_reason: str
    escalation_strategy: EscalationStrategy
    metadata: Dict[str, Any]


SelectorManifest = List[SelectorManifestRecord]
