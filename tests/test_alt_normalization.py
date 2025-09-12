from core.pptx_alt_injector import PPTXAltTextInjector
from core.pptx_processor import PPTXAccessibilityProcessor


def test_normalize_alt_universal_sentence_termination():
    injector = PPTXAltTextInjector()
    assert injector._normalize_alt_universal("A blue square.") == "A blue square."
    assert injector._normalize_alt_universal("A red circle") == "A red circle."


def test_normalize_alt_preserves_punctuation():
    injector = PPTXAltTextInjector()
    processor = PPTXAccessibilityProcessor.__new__(PPTXAccessibilityProcessor)
    text = injector._normalize_alt_universal("A red circle")
    assert processor._normalize_alt(text) == text
    assert processor._normalize_alt("A blue square.") == "A blue square."

