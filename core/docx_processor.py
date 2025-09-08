#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
docx_processor.py
-----------------
ALT text processor for Word (.docx) with a callable function and CLI compatible
with `batch_processor.py`. It uses `unified_alt_generator` if available; otherwise
falls back to a conservative built-in generator.

Key behaviors:
- Scans a .docx for drawing images and sets ALT text on wp:docPr[@descr].
- Decorative filtering (size threshold + keyword overrides) guided by config.yaml.
- Preserves original document (optional via config).
- Emits a result dict with coverage counts.
- CLI supports: --input, --output, --config

Dependencies:
- python-docx (install: pip install python-docx)
- PyYAML (if you don't use config_manager.py)

Caveats:
- Word's ALT text is carried in wp:docPr attributes "descr" (and optionally "title").
- We compute a basic mapping from drawings -> related image parts via r:embed relationship,
  so we can pass the actual image bytes to the ALT generator when available.
"""
from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import json
import logging
import os
import shutil
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# -----------------------------
# Config loading (config_manager -> yaml fallback)
# -----------------------------
def load_config(config_path: Path) -> Dict[str, Any]:
    cfg = {}
    with contextlib.suppress(Exception):
        cm = importlib.import_module("config_manager")
        if hasattr(cm, "load_config"):
            return cm.load_config(str(config_path))
    try:
        import yaml  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "Could not import config_manager or PyYAML. Install PyYAML or provide config_manager.py"
        ) from e
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return cfg

# -----------------------------
# Logger
# -----------------------------
def setup_logging(level_name: str = "INFO") -> logging.Logger:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logger = logging.getLogger("docx_processor")
    logger.setLevel(level)
    logger.handlers.clear()
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(ch)
    return logger

# -----------------------------
# ALT generator bridge
# -----------------------------
def generate_alt_text(image_bytes: bytes, cfg: Dict[str, Any], context: str = "") -> str:
    """
    Try to route through `unified_alt_generator` if present. Otherwise, use a
    built-in deterministic fallback description.
    """
    with contextlib.suppress(Exception):
        gen = importlib.import_module("unified_alt_generator")
        if hasattr(gen, "generate_alt_text"):
            # Expected signature: (image_bytes|path, config, context="")
            return gen.generate_alt_text(image_bytes, cfg, context=context)
        if hasattr(gen, "infer_alt_text"):
            return gen.infer_alt_text(image_bytes, cfg, context=context)
    # Fallback: conservative
    return "Illustration relevant to the surrounding text."

# -----------------------------
# Word processing
# -----------------------------
def _nsmap():
    return {
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
        "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    }

def _emu_to_px(emu: int, dpi: int = 96) -> int:
    # 1 inch = 914400 EMUs; 1 inch = dpi px
    return int((emu / 914400.0) * dpi)

def _shape_area_from_drawing(drawing) -> int:
    """
    Estimate shape size in pixels^2 from wp:extent @cx,@cy.
    """
    try:
        ext = drawing.xpath(".//wp:extent", namespaces=_nsmap())
        if ext:
            cx = int(ext[0].get("cx", "0"))
            cy = int(ext[0].get("cy", "0"))
            return _emu_to_px(cx) * _emu_to_px(cy)
    except Exception:
        pass
    return 0

def _is_decorative(docpr_el, drawing, cfg: Dict[str, Any]) -> bool:
    # Keyword / filename heuristics
    overrides = (cfg.get("decorative_overrides") or {})
    contains = (overrides.get("decorative_rules") or {}).get("contains") or []
    exact = (overrides.get("decorative_rules") or {}).get("exact") or []
    force_decor = set(overrides.get("force_decorative") or [])
    never_decor = set(overrides.get("never_decorative") or [])

    name = (docpr_el.get("name") or "").lower()
    descr = (docpr_el.get("descr") or "").lower()
    shape_text = f"{name} {descr}".strip()

    for token in never_decor:
        if token in shape_text:
            return False

    for token in force_decor:
        if token in shape_text:
            return True

    for token in contains:
        if token.lower() in shape_text:
            return True

    for token in exact:
        if token.lower() == name or token.lower() == descr:
            return True

    # Size threshold (px)
    threshold = int(((cfg.get("pptx_processing") or {}).get("decorative_size_threshold")) or 50)
    area = _shape_area_from_drawing(drawing)
    if area and area < (threshold * threshold):
        return True
    return False

def _iter_drawing_docPr(document) -> List[Tuple[Any, Any, str]]:
    """
    Yield (docPr_element, drawing_element, rel_id) for each image drawing.
    """
    ns = _nsmap()
    body = document.element.body
    for drawing in body.xpath(".//w:drawing", namespaces=ns):
        docPr = drawing.xpath(".//wp:docPr", namespaces=ns)
        if not docPr:
            continue
        docPr = docPr[0]
        # Relationship id on a:blip
        blips = drawing.xpath(".//a:blip", namespaces=ns)
        rel_id = None
        if blips:
            rel_id = blips[0].get("{%s}embed" % ns["r"])
        yield (docPr, drawing, rel_id)

def _image_bytes_for_rel(document, rel_id: Optional[str]) -> Optional[bytes]:
    if not rel_id:
        return None
    part = document.part
    with contextlib.suppress(KeyError):
        rel = part.rels[rel_id]
        if hasattr(rel, "target_part") and hasattr(rel.target_part, "blob"):
            return rel.target_part.blob
    return None

def _get_context_text(document) -> str:
    # Simple context: concatenate paragraph texts up to a limit
    texts = [p.text for p in document.paragraphs if p.text]
    ctx = " ".join(texts[:50])  # lightweight
    return ctx[:500]

def process_docx(input_path: str, output_path: str, cfg: Dict[str, Any], logger: Optional[logging.Logger] = None) -> Dict[str, Any]:
    from docx import Document  # import here to avoid hard dependency on environments without it

    t0 = time.time()
    if logger is None:
        logger = setup_logging((cfg.get("logging") or {}).get("level") or "INFO")

    # Prepare output directory
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Preserve original if requested
    preserve = ((cfg.get("pptx_processing") or {}).get("preserve_original") is True)
    if preserve:
        bak = out_path.with_suffix(out_path.suffix + ".bak")
        with contextlib.suppress(Exception):
            shutil.copy2(input_path, bak)

    doc = Document(input_path)
    ctx = _get_context_text(doc)

    total_imgs = 0
    updated = 0
    skipped_decor = 0

    for docPr, drawing, rel_id in _iter_drawing_docPr(doc):
        total_imgs += 1
        if _is_decorative(docPr, drawing, cfg):
            # Intentionally clear ALT for decorative items
            docPr.set("descr", "")
            skipped_decor += 1
            continue

        img_bytes = _image_bytes_for_rel(doc, rel_id)
        alt_text = generate_alt_text(img_bytes or b"", cfg, context=ctx)
        # Respect output char limit if configured
        char_limit = int(((cfg.get("output") or {}).get("char_limit")) or 125)
        if len(alt_text) > char_limit:
            alt_text = alt_text[:char_limit].rstrip() + "."
        docPr.set("descr", alt_text)
        updated += 1

    doc.save(out_path)

    duration = time.time() - t0
    result = {
        "file": str(input_path),
        "output": str(out_path),
        "success": True,
        "stats": {
            "file_type": "docx",
            "elements_total": total_imgs,
            "elements_with_alt": updated,
            "elements_decorative": skipped_decor,
            "coverage": float(updated) / float(total_imgs) if total_imgs else 1.0,
            "duration_sec": duration,
        },
    }
    return result

# Backward-compat alias for the batch adapter
def process_file(input_path: str, output_path: str, config: Dict[str, Any], logger: Optional[logging.Logger] = None) -> Dict[str, Any]:
    return process_docx(input_path, output_path, config, logger=logger)

def _cli(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="DOCX ALT text processor")
    ap.add_argument("--input", "-i", required=True, help="Input .docx file")
    ap.add_argument("--output", "-o", required=True, help="Output .docx file")
    ap.add_argument("--config", "-c", default="config.yaml", help="Path to config.yaml")
    args = ap.parse_args(argv)

    cfg = load_config(Path(args.config))
    logger = setup_logging((cfg.get("logging") or {}).get("level") or "INFO")

    res = process_docx(args.input, args.output, cfg, logger=logger)
    # Print a JSON line so parent batcher can optionally parse it
    print(json.dumps(res, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(_cli())
