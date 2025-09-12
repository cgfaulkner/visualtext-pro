from docx import Document

from shared.alt_manifest import AltManifestEntry
from shared.manifest_docx_builder import _create_review_table


def test_preserved_alt_falls_back_to_final_alt():
    entry = AltManifestEntry(
        key="slide_1_shape_1",
        image_hash="hash1",
        final_alt="Existing ALT",
        decision_reason="preserved",
        source="existing",
    )
    entry.had_existing_alt = True

    doc = Document()
    table = _create_review_table(doc, [entry], portrait=True)

    assert table.rows[1].cells[3].text == "Existing ALT"

