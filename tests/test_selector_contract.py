"""Tests for Smart Selector contract and shape-built diagram clustering."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES_DIR = ROOT / "fixtures" / "selector"
SCHEMA_PATH = ROOT / "schemas" / "selector_manifest.schema.json"


def _load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _run_selector_with_fixture(fixture_name: str, config: dict):
    """Run selector using fixture visual_index; return manifest list."""
    from shared.pipeline_artifacts import RunArtifacts
    from shared.selector.selector import run_selector

    fixture_dir = FIXTURES_DIR / fixture_name
    visual_index_path = fixture_dir / "visual_index.json"
    if not visual_index_path.exists():
        pytest.skip(f"Fixture {fixture_name} has no visual_index.json")
    visual_index = _load_json(visual_index_path)

    # Use a temp run dir and wire artifacts to fixture data
    import tempfile
    run_dir = Path(tempfile.mkdtemp())
    try:
        scan_dir = run_dir / "scan"
        scan_dir.mkdir(parents=True)
        selector_dir = run_dir / "selector"
        selector_dir.mkdir(parents=True)
        with open(scan_dir / "visual_index.json", "w", encoding="utf-8") as f:
            json.dump(visual_index, f, indent=2, ensure_ascii=False)
        with open(scan_dir / "current_alt_by_key.json", "w", encoding="utf-8") as f:
            json.dump({}, f)

        artifacts = RunArtifacts(
            run_dir=run_dir,
            session_id="test",
            current_alt_by_key_path=scan_dir / "current_alt_by_key.json",
            visual_index_path=scan_dir / "visual_index.json",
            thumbs_dir=run_dir / "thumbs",
            crops_dir=run_dir / "crops",
            manifest_path=run_dir / "manifest.json",
            selector_manifest_path=selector_dir / "selector_manifest.json",
            generated_alt_by_key_path=run_dir / "generate" / "generated_alt_by_key.json",
            alt_status_by_key_path=run_dir / "generate" / "alt_status_by_key.json",
            final_alt_map_path=run_dir / "resolve" / "final_alt_map.json",
            cleanup_on_exit=False,
        )
        (run_dir / "generate").mkdir(exist_ok=True)
        (run_dir / "resolve").mkdir(exist_ok=True)
        (run_dir / "thumbs").mkdir(exist_ok=True)
        (run_dir / "crops").mkdir(exist_ok=True)

        # Non-existent PPTX so parent_map is empty (all top-level)
        pptx_path = Path("/nonexistent/fixture.pptx")
        run_selector(pptx_path, artifacts, config, output_path=artifacts.selector_manifest_path)
        with open(artifacts.selector_manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    finally:
        import shutil
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)


@pytest.fixture
def selector_config():
    """Config with synthetic_diagram enabled."""
    return {
        "selector": {
            "enabled": True,
            "synthetic_diagram": {
                "enabled": True,
                "proximity_px": 40,
                "required_alignment_fraction": 0.6,
                "confidence_threshold": 0.6,
            },
            "placeholder_alt_patterns": [],
            "min_meaningful_alt_chars": 15,
        },
        "alt_text_handling": {"mode": "preserve"},
    }


def test_group_line_diagram_produces_single_virtual_group(selector_config):
    """Arrows + 2 labels -> single include_group with children exclude_redundant."""
    manifest = _run_selector_with_fixture("group_line_diagram", selector_config)
    golden_path = FIXTURES_DIR / "group_line_diagram" / "selector_manifest.json.golden"
    golden = _load_json(golden_path)

    include_group = [r for r in manifest if r["selector_decision"] == "include_group"]
    assert len(include_group) == 1, "Expected one include_group (anchor)"
    assert include_group[0]["reason_code"] == "include_group_synthetic_diagram"
    assert include_group[0]["element_id"] == "slide_0_shape_1"

    exclude_redundant = [r for r in manifest if r["selector_decision"] == "exclude_redundant"]
    assert len(exclude_redundant) == 4, "Expected 4 members exclude_redundant"
    for r in exclude_redundant:
        assert r["parent_group_id"] == "slide_0_shape_1"

    # Order-independent comparison of key fields
    assert len(manifest) == len(golden)
    by_id = {r["element_id"]: r for r in manifest}
    for g in golden:
        eid = g["element_id"]
        assert eid in by_id, f"Missing element {eid}"
        m = by_id[eid]
        assert m["selector_decision"] == g["selector_decision"]
        assert m["reason_code"] == g["reason_code"]
        if g.get("parent_group_id") is not None:
            assert m["parent_group_id"] == g["parent_group_id"]


def test_decorative_lines_no_grouping(selector_config):
    """Parallel lines, no connectors/labels -> no group; individual exclude_decorative."""
    manifest = _run_selector_with_fixture("decorative_lines", selector_config)
    golden_path = FIXTURES_DIR / "decorative_lines" / "selector_manifest.json.golden"
    golden = _load_json(golden_path)

    include_group = [r for r in manifest if r["selector_decision"] == "include_group"]
    assert len(include_group) == 0, "Expected no synthetic group for decorative lines"

    assert len(manifest) == len(golden)
    by_id = {r["element_id"]: r for r in manifest}
    for g in golden:
        eid = g["element_id"]
        assert eid in by_id
        assert by_id[eid]["selector_decision"] == g["selector_decision"]


def test_connector_labeled_diagram_connector_suffices(selector_config):
    """Connector present, single label -> connector suffices to group."""
    manifest = _run_selector_with_fixture("connector_labeled_diagram", selector_config)
    golden_path = FIXTURES_DIR / "connector_labeled_diagram" / "selector_manifest.json.golden"
    golden = _load_json(golden_path)

    include_group = [r for r in manifest if r["selector_decision"] == "include_group"]
    assert len(include_group) == 1
    assert include_group[0]["element_id"] == "slide_0_shape_20"

    exclude_redundant = [r for r in manifest if r["selector_decision"] == "exclude_redundant"]
    assert len(exclude_redundant) == 2
    assert len(manifest) == len(golden)


def test_golden_manifests_validate_against_schema():
    """All golden selector manifests in fixtures validate against schema."""
    import jsonschema
    if not SCHEMA_PATH.exists():
        pytest.skip("Schema not found")
    schema = _load_json(SCHEMA_PATH)
    resolver = jsonschema.RefResolver(
        base_uri=f"file://{SCHEMA_PATH.resolve()}",
        referrer=schema,
    )
    for name in ["group_line_diagram", "decorative_lines", "connector_labeled_diagram",
                 "group_basic", "overlay_arrow_on_image", "placeholder_alt_cases"]:
        golden_path = FIXTURES_DIR / name / "selector_manifest.json.golden"
        if not golden_path.exists():
            continue
        manifest = _load_json(golden_path)
        jsonschema.validate(instance=manifest, schema=schema, resolver=resolver)
