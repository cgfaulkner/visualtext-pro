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
import hashlib
import importlib
import json
import logging
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple
from docx.oxml.ns import qn

LOCKFILE_PREFIXES = ("~$", "._")  # Office lock files & macOS dotfiles

def _is_lockfile(path: Path) -> bool:
    return path.name.startswith(LOCKFILE_PREFIXES)

# -----------------------------
# Config loading (config_manager -> yaml fallback)
# -----------------------------
def load_config(config_path: Path) -> Dict[str, Any]:
    for name in ("config_manager", "shared.config_manager"):
        with contextlib.suppress(Exception):
            cm = importlib.import_module(name)
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
def setup_logging(level: str = "INFO", log_dir: str = None) -> logging.Logger:
    logger = logging.getLogger("docx_processor")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Avoid duplicate handlers if called twice
    if logger.handlers:
        return logger

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    # Console
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logger.level)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # File handler to /logs
    try:
        root = Path(__file__).resolve().parents[1]  # project root
        logs_dir = Path(log_dir).resolve() if log_dir else (root / "logs")
        logs_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(logs_dir / "docx_processor.log"), encoding="utf-8")
        fh.setLevel(logger.level)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        # Don't crash on logging setup
        pass

    return logger

# -----------------------------
# ALT generator bridge
# -----------------------------
def generate_alt_text(image_bytes: bytes, cfg: dict, context: str = "") -> str:
    import importlib, logging
    logger = logging.getLogger("docx_processor")
    for modname in ("shared.unified_alt_generator", "unified_alt_generator"):
        try:
            gen = importlib.import_module(modname)
            if hasattr(gen, "generate_alt_text"):
                logger.debug(f"DOCX using {modname}.generate_alt_text")
                return gen.generate_alt_text(image_bytes, cfg, context=context)
            if hasattr(gen, "generate_alt_text_unified"):
                logger.debug(f"DOCX using {modname}.generate_alt_text_unified (direct)")
                return gen.generate_alt_text_unified(image_bytes, cfg, context=context)
        except Exception as e:
            logger.debug(f"Generator import failed for {modname}: {e}", exc_info=True)
    raise RuntimeError("No generate_alt_text(_unified) found in unified_alt_generator.")

# -----------------------------
# Word processing
# -----------------------------

def _emu_to_px(emu: int, dpi: int = 96) -> int:
    # 1 inch = 914400 EMUs; 1 inch = dpi px
    return int((emu / 914400.0) * dpi)

def _shape_area_from_drawing(drawing) -> int:
    """
    Estimate shape size in pixels^2 from wp:extent @cx,@cy.
    """
    try:
        ext = drawing.xpath(".//wp:extent")
        if ext:
            cx = int(ext[0].get("cx", "0"))
            cy = int(ext[0].get("cy", "0"))
            return _emu_to_px(cx) * _emu_to_px(cy)
    except Exception:
        pass
    return 0

def _is_decorative(docpr_el, drawing, cfg: Dict[str, Any]) -> bool:
    # size proxy
    area = _shape_area_from_drawing(drawing)
    name = (docpr_el.get("name") or "")
    descr = (docpr_el.get("descr") or "")
    meta = f"{name} {descr}".strip()
    
    # Delegate to shared decorative filter (same rules as PPTX)
    try:
        with contextlib.suppress(Exception):
            deco = importlib.import_module("shared.decorative_filter")
            if hasattr(deco, "is_decorative"):
                return deco.is_decorative(meta=meta, pixel_area=area, config=cfg, platform="docx")
            elif hasattr(deco, "is_force_decorative_by_filename"):
                return deco.is_force_decorative_by_filename(meta, cfg)
    except Exception:
        pass
    
    # Fallback to original logic
    overrides = (cfg.get("decorative_overrides") or {})
    contains = (overrides.get("decorative_rules") or {}).get("contains") or []
    exact = (overrides.get("decorative_rules") or {}).get("exact") or []
    force_decor = set(overrides.get("force_decorative") or [])
    never_decor = set(overrides.get("never_decorative") or [])

    name_lower = name.lower()
    descr_lower = descr.lower()
    shape_text = f"{name_lower} {descr_lower}".strip()

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
        if token.lower() == name_lower or token.lower() == descr_lower:
            return True

    # Size threshold (px)
    threshold = int(((cfg.get("pptx_processing") or {}).get("decorative_size_threshold")) or 50)
    if area and area < (threshold * threshold):
        return True
    return False

def _iter_drawing_docPr(document) -> Iterator[Tuple[Any, Any, Optional[str], str]]:
    """
    Yield (docPr, drawing, rel_id, location_tag) for each image in body and headers/footers.
    """
    # Body
    body = document.element.body
    for drawing in body.xpath(".//w:drawing"):
        docPrs = drawing.xpath(".//wp:docPr")
        if not docPrs: 
            continue
        blips = drawing.xpath(".//a:blip")
        rel_id = blips[0].get(qn("r:embed")) if blips else None
        yield (docPrs[0], drawing, rel_id, "body")

    # Headers/Footers
    for sec in document.sections:
        if sec.header and sec.header._element is not None:
            for drawing in sec.header._element.xpath(".//w:drawing"):
                docPrs = drawing.xpath(".//wp:docPr")
                if not docPrs: continue
                blips = drawing.xpath(".//a:blip")
                rel_id = blips[0].get(qn("r:embed")) if blips else None
                yield (docPrs[0], drawing, rel_id, "header")

        if sec.footer and sec.footer._element is not None:
            for drawing in sec.footer._element.xpath(".//w:drawing"):
                docPrs = drawing.xpath(".//wp:docPr")
                if not docPrs: continue
                blips = drawing.xpath(".//a:blip")
                rel_id = blips[0].get(qn("r:embed")) if blips else None
                yield (docPrs[0], drawing, rel_id, "footer")

def _image_bytes_for_rel(document, rel_id: Optional[str]) -> Optional[bytes]:
    if not rel_id:
        return None
    part = document.part
    with contextlib.suppress(KeyError, AttributeError):
        rel = part.rels[rel_id]
        tpart = getattr(rel, "target_part", None)
        if not tpart:
            return None
        # Only process actual images
        ctype = getattr(tpart, "content_type", "")
        if not isinstance(ctype, str) or not ctype.startswith("image/"):
            return None
        blob = getattr(tpart, "blob", None)
        return blob if blob else None
    return None

def _hash_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


def _collect_context(document, docPr_elem) -> str:
    # Nearby textual context: first N non-empty paragraphs in doc
    texts = []
    for p in document.paragraphs:
        if p.text and p.text.strip():
            texts.append(p.text.strip())
        if len(texts) >= 40:
            break
    base = " ".join(texts)[:800]

    # Add docPr hints (name/title/descr if any)
    name = (docPr_elem.get("name") or "").strip()
    descr = (docPr_elem.get("descr") or "").strip()
    meta = " ".join(x for x in [name, descr] if x).strip()

    ctx = (meta + " " + base).strip() if meta else base
    return ctx[:1000]

def _finalize_alt(text: str, cfg: Dict[str, Any]) -> str:
    # Try using alt_cleaner from shared module
    try:
        with contextlib.suppress(Exception):
            alt_cleaner = importlib.import_module("shared.alt_cleaner")
            if hasattr(alt_cleaner, "clean_alt_text"):
                text = alt_cleaner.clean_alt_text(text)
            elif hasattr(alt_cleaner, "clean_text"):
                text = alt_cleaner.clean_text(text, cfg)
    except Exception:
        pass
    
    # char limit from config
    char_limit = int(((cfg.get("output") or {}).get("char_limit")) or 125)
    text = (text[:char_limit]).rstrip()
    if text and text[-1] not in ".!?":
        text += "."
    return text

def process_docx(input_path: str,
                 output_path: Optional[str],
                 cfg: Dict[str, Any],
                 logger: Optional[logging.Logger] = None,
                 inplace: Optional[bool] = None,
                 backup: bool = True) -> Dict[str, Any]:
    from docx import Document

    t0 = time.time()
    if logger is None:
        log_cfg = cfg.get("logging") or {}
        logger = setup_logging(log_cfg.get("level") or "INFO", log_cfg.get("dir"))

    in_path = Path(input_path).expanduser().resolve()
    if _is_lockfile(in_path):
        raise RuntimeError(f"Refusing to process Office lock file: {in_path.name}")

    # Decide in-place vs explicit output (be robust to None output_path)
    if inplace is None:
        same_path = False
        if output_path:
            try:
                same_path = (Path(output_path).expanduser().resolve() == in_path)
            except Exception:
                same_path = False
        inplace = (output_path is None) or same_path
    else:
        # If caller forced inplace=False but gave no output, override to True to avoid NonePath errors
        if output_path is None and inplace is False:
            inplace = True

    # Determine final output target
    if inplace:
        out_final = in_path
    else:
        out_final = Path(output_path).expanduser().resolve()
        out_final.parent.mkdir(parents=True, exist_ok=True)

    # Load
    doc = Document(str(in_path))
    
    # Initialize counters and cache
    total_imgs = 0
    updated = 0
    skipped_decor = 0
    llava_calls = 0
    warnings = []
    alt_cache: Dict[str, str] = {}

    for docPr, drawing, rel_id, location in _iter_drawing_docPr(doc):
        total_imgs += 1

        if _is_decorative(docPr, drawing, cfg):
            docPr.set("descr", "")
            skipped_decor += 1
            continue

        # Check if we should respect existing ALT text
        respect_existing = bool((cfg.get("output") or {}).get("respect_existing_alt", False))
        existing = (docPr.get("descr") or "").strip()
        if respect_existing and existing:
            # count it as updated but don't call LLaVA
            updated += 1
            continue

        bytes_ = _image_bytes_for_rel(doc, rel_id)
        if not bytes_:
            warnings.append(f"no_image_bytes:{location}:{rel_id or 'none'}")
            continue

        img_key = _hash_bytes(bytes_)
        if img_key in alt_cache:
            alt = alt_cache[img_key]
        else:
            ctx = _collect_context(doc, docPr)
            t0 = time.time()
            alt_raw = generate_alt_text(bytes_, cfg, context=ctx)  # <- must NOT fallback silently unless you set allow_docx_fallback_alt
            took_ms = int((time.time() - t0) * 1000)
            llava_calls += 1
            logger.debug(f"DOCX LLaVA call #{llava_calls} [{location}] rid={rel_id} hash={img_key} ctx={len(ctx)}B took={took_ms}ms")
            alt = _finalize_alt(alt_raw, cfg)
            alt_cache[img_key] = alt

        docPr.set("descr", alt)
        updated += 1

    # Save atomically
    #  - write to temp in the same directory for atomic cross-device replace
    #  - optional .bak backup if doing in-place
    out_dir = out_final.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    # Backup original if in-place and requested
    if inplace and backup:
        bak = out_final.with_suffix(out_final.suffix + ".bak")
        try:
            shutil.copy2(out_final, bak)
        except Exception:
            logger.debug("Backup copy failed (continuing without backup).", exc_info=True)

    # Write temp then replace
    with tempfile.NamedTemporaryFile(delete=False, dir=str(out_dir), suffix=out_final.suffix) as tmp:
        tmp_path = Path(tmp.name)
    try:
        doc.save(str(tmp_path))
        os.replace(str(tmp_path), str(out_final))  # atomic on same filesystem
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()

    duration = time.time() - t0
    return {
        "file": str(in_path),
        "output": str(out_final),
        "success": True,
        "stats": {
            "file_type": "docx",
            "elements_total": total_imgs,
            "elements_with_alt": updated,
            "elements_decorative": skipped_decor,
            "coverage": float(updated) / float(total_imgs) if total_imgs else 1.0,
            "duration_sec": duration,
            "inplace": inplace,
            "backup_created": bool(inplace and backup),
            "llava_calls": llava_calls,
            "unique_images": len(alt_cache),
            "warnings": warnings,
        },
    }

# Backward-compat alias for the batch adapter
def process_file(input_path: str,
                 output_path: Optional[str],
                 config: Dict[str, Any],
                 logger: Optional[logging.Logger] = None,
                 **kwargs) -> Dict[str, Any]:
    return process_docx(input_path, output_path, config, logger=logger, **kwargs)

def _cli(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="DOCX ALT text processor (in-place supported)")
    ap.add_argument("--input", "-i", required=True, help="Input .docx file")
    ap.add_argument("--output", "-o", help="Output .docx file. If omitted or equal to input, runs in-place.")
    ap.add_argument("--config", "-c", default="config.yaml", help="Path to config.yaml")
    ap.add_argument("--inplace", action="store_true", help="Process in place (overwrite the input file).")
    ap.add_argument("--no-backup", action="store_true", help="Do not write a .bak before in-place replace.")
    args = ap.parse_args(argv)

    # If no --output was provided and user didn't pass --inplace, default to in-place
    if args.output is None and not args.inplace:
        args.inplace = True

    cfg = load_config(Path(args.config))
    log_cfg = cfg.get("logging") or {}
    logger = setup_logging(log_cfg.get("level") or "INFO", log_cfg.get("dir"))

    res = process_docx(
        args.input,
        args.output,
        cfg,
        logger=logger,
        inplace=args.inplace,
        backup=(not args.no_backup),
    )
    print(json.dumps(res, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(_cli())
