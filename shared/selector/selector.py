"""Smart Selector - Main implementation."""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List

from .types import (
    SelectorManifestRecord,
    SelectorManifest,
    SelectorDecision,
    ContentScope,
    EscalationStrategy,
)

logger = logging.getLogger(__name__)

SELECTOR_VERSION = "1.0-rc2"


def _get_shape_type_name(shape) -> str:
    """Extract shape type name from python-pptx shape object."""
    try:
        from pptx.enum.shapes import MSO_SHAPE_TYPE

        shape_type_map = {
            MSO_SHAPE_TYPE.PICTURE: "PICTURE",
            MSO_SHAPE_TYPE.AUTO_SHAPE: "AUTO_SHAPE",
            MSO_SHAPE_TYPE.GROUP: "GROUP",
            MSO_SHAPE_TYPE.CHART: "CHART",
            MSO_SHAPE_TYPE.SMARTART: "SMARTART",
            MSO_SHAPE_TYPE.MEDIA: "MEDIA",
            MSO_SHAPE_TYPE.TEXT_BOX: "TEXT_BOX",
            MSO_SHAPE_TYPE.WORDART: "WORDART",
            MSO_SHAPE_TYPE.OLE_CONTROL_OBJECT: "OLE_OBJECT",
            MSO_SHAPE_TYPE.TABLE: "TABLE",
        }

        shape_type = getattr(shape, "shape_type", None)
        if shape_type in shape_type_map:
            return shape_type_map[shape_type]
        return "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def _extract_candidate_elements(pptx_path: Path) -> List[Dict[str, Any]]:
    """
    Extract candidate visual elements from PPTX file.
    
    Returns list of candidate element dictionaries with:
    - slide_idx: int
    - shape_idx: int
    - shape: python-pptx shape object
    - shape_type: str
    """
    try:
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE

        prs = Presentation(str(pptx_path))
        candidates = []

        for slide_idx, slide in enumerate(prs.slides):
            for shape_idx, shape in enumerate(slide.shapes):
                # Skip empty placeholder text boxes
                try:
                    if (
                        hasattr(shape, "is_placeholder")
                        and shape.is_placeholder
                        and hasattr(shape, "placeholder_format")
                        and shape.placeholder_format.type == 7  # TEXT type
                        and not shape.text.strip()
                    ):
                        continue
                except Exception:
                    pass

                shape_type = _get_shape_type_name(shape)
                candidates.append(
                    {
                        "slide_idx": slide_idx,
                        "shape_idx": shape_idx,
                        "shape": shape,
                        "shape_type": shape_type,
                    }
                )

        return candidates
    except Exception as e:
        logger.error(f"Error extracting candidate elements: {e}", exc_info=True)
        return []


def run_selector(pptx_path: Path, config: Dict[str, Any], output_path: Path | None = None) -> Path:
    """
    Run the Smart Selector on a PPTX file.
    
    Args:
        pptx_path: Path to PPTX file
        config: Configuration dictionary (may contain selector.* keys)
        output_path: Optional path to write selector_manifest.json. If None, uses config or default.
        
    Returns:
        Path to written selector_manifest.json file
        
    The selector writes a schema-valid JSON manifest with decision records
    for each candidate visual element. In stub v1.0-rc2, all elements are
    included as atomic with reason_code "stub_v1".
    """
    logger.info(f"Running Smart Selector v{SELECTOR_VERSION} on {pptx_path.name}")

    # Extract candidate elements
    candidates = _extract_candidate_elements(pptx_path)
    logger.info(f"Found {len(candidates)} candidate visual elements")

    # Generate stub decisions for all candidates
    manifest: SelectorManifest = []
    decision_counts: Dict[str, int] = {}

    for candidate in candidates:
        slide_idx = candidate["slide_idx"]
        shape_idx = candidate["shape_idx"]
        shape_type = candidate["shape_type"]

        # Generate stable element_id
        element_id = f"slide_{slide_idx}_shape_{shape_idx}"

        # Create stub decision record
        record: SelectorManifestRecord = {
            "selector_version": SELECTOR_VERSION,
            "element_id": element_id,
            "parent_group_id": None,  # Stub: will be set when group logic is implemented
            "selector_decision": "include_atomic",  # Stub decision
            "content_scope": "image",  # Stub scope
            "reason_code": "stub_v1",
            "human_reason": "Stub v1: included for processing",
            "escalation_strategy": "none",  # Stub: no escalation
            "metadata": {
                "original_shape_type": shape_type,
            },
        }

        manifest.append(record)

        # Count decisions
        decision = record["selector_decision"]
        decision_counts[decision] = decision_counts.get(decision, 0) + 1

    # Sort manifest by element_id for deterministic output
    manifest.sort(key=lambda r: r["element_id"])

    # Log decision counts
    logger.info(f"Selector decisions: {dict(decision_counts)}")
    logger.info(f"Total decisions: {len(manifest)}")

    # Determine output path: use provided path, then config, then default
    if output_path is None:
        output_dir = config.get("selector", {}).get("output_dir")
        if output_dir:
            output_path = Path(output_dir) / "selector_manifest.json"
        else:
            # Default: write to same directory as PPTX
            output_path = pptx_path.parent / "selector_manifest.json"
    else:
        output_path = Path(output_path)
    
    # Ensure parent directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write manifest to JSON file
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    logger.info(f"Selector manifest written to {output_path}")
    return output_path
