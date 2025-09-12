"""Concept detection utilities for slide notes."""

known_concepts = {
    "time constant": "Time Constant",
    "conduction velocity": "Conduction Velocity",
    "resting potential": "Resting Potential",
    "membrane potential": "Membrane Potential",
    "nerve conduction": "Nerve Conduction Studies",
    "action potential": "Action Potential",
    "depolarization": "Depolarization",
    "sodium channels": "Sodium Channel Dynamics",
    "potassium channels": "Potassium Channel Dynamics",
}


def detect_concept_from_notes(notes: str) -> str:
    """Return a concept tag if notes contain a known keyword.

    Args:
        notes: Text from slide notes.

    Returns:
        Detected concept name or an empty string if none match.
    """
    for keyword, concept in known_concepts.items():
        if keyword in notes.lower():
            return concept
    return ""
