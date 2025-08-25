import yaml
import os

class ConceptDetector:
    """Detect educational concepts from text using a YAML definition file."""

    def __init__(self, concept_file: str = "concepts.yaml") -> None:
        """Load concept definitions and build keyword map."""
        self.concept_data = {}
        self.keyword_map = {}
        self._load_concepts(concept_file)

    def _load_concepts(self, filepath: str) -> None:
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Concept file not found: {filepath}")

        with open(filepath, "r", encoding="utf-8") as f:
            self.concept_data = yaml.safe_load(f) or {}

        for concept, info in self.concept_data.items():
            for keyword in info.get("keywords", []):
                self.keyword_map[keyword.lower()] = concept

    def detect(self, text: str):
        """Return a list of concepts found in the provided text."""
        found = []
        lowered = text.lower()
        for keyword, concept in self.keyword_map.items():
            if keyword in lowered:
                found.append(concept)
        return list(set(found))

    def describe(self, concept: str) -> str:
        """Return the description for a given concept."""
        return self.concept_data.get(concept, {}).get("description", "")
