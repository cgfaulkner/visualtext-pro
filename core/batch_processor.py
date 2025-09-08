#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
batch_processor.py
------------------
Unified batch processor for mixed Office documents (.pptx and .docx).

Features
- Folder scanning (recursive optional) for .pptx and .docx
- Automatic routing to appropriate processors:
    - PPTX -> pptx_alt_processor.py (import or subprocess)
    - DOCX -> docx_processor.py (import or subprocess)
- Real-time unified progress with ETA and throughput
- CLI: python batch_processor.py --folder /path/input --output /path/out [--recursive] [--skip-existing]
- Error handling: continues on failure; logs errors and produces a unified JSON report
- Uses config.yaml (via config_manager if available, else PyYAML)
- Logging consistent with typical patterns (INFO to console; optional file in output dir)
- Maintains folder structure in output; handles duplicate filenames; option to skip existing
- Generates combined coverage report (JSON) across both document types

Assumptions / Compatibility
- For PPTX: we attempt to call one of these functions if available:
    - process_file(input_path, output_path, config=None, logger=None)
    - process_pptx(input_path, output_path, config=None, logger=None)
  Otherwise we fall back to running 'pptx_alt_processor.py' as a CLI with common flag patterns.
- For DOCX: `docx_processor.py` provided alongside includes a compatible `process_file(...)` and CLI.
- If your existing PPTX processor already emits a per-file JSON report, this script will try to find it
  in the output directory and merge coverage stats automatically.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import contextlib
import importlib
import io
import json
import logging
import os
import queue
import shlex
import signal
import subprocess
import sys
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# -----------------------------
# Config loading (config_manager -> yaml fallback)
# -----------------------------
def load_config(config_path: Path) -> Dict[str, Any]:
    cfg = {}
    # Preferred: a local config_manager module provided by the project
    with contextlib.suppress(Exception):
        cm = importlib.import_module("config_manager")
        if hasattr(cm, "load_config"):
            return cm.load_config(str(config_path))
    # Fallback: PyYAML
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
# Logging setup
# -----------------------------
def setup_logging(output_dir: Path, cfg: Dict[str, Any]) -> logging.Logger:
    level_name = (((cfg or {}).get("logging") or {}).get("level") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logger = logging.getLogger("batch_processor")
    logger.setLevel(level)
    logger.handlers.clear()

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(ch)

    # Optional file handler
    log_to_file = ((cfg.get("logging") or {}).get("log_to_file") is True)
    if log_to_file:
        output_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(output_dir / "batch_processor.log", encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(fh)

    # Extra diagnostics if requested in config
    log_cfg = cfg.get("logging") or {}
    if log_cfg.get("log_configuration"):
        logger.info("Loaded configuration keys: %s", list(cfg.keys()))
    return logger

# -----------------------------
# Utility helpers
# -----------------------------
SUPPORTED_EXTS = {".pptx", ".docx"}

def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTS

def discover_files(root: Path, recursive: bool) -> List[Path]:
    if recursive:
        return [p for p in root.rglob("*") if p.is_file() and is_supported(p)]
    else:
        return [p for p in root.glob("*") if p.is_file() and is_supported(p)]

def rel_output_path(infile: Path, input_root: Path, output_root: Path) -> Path:
    """
    Mirror the input directory structure under the output root.
    Ensure directory exists; avoid name collisions by suffixing if needed.
    """
    rel = infile.relative_to(input_root)
    out_path = output_root / rel
    out_dir = out_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    # If a duplicate filename arises (e.g., because of case-insensitive FS), suffix it.
    if out_path.exists():
        stem, ext = out_path.stem, out_path.suffix
        i = 1
        while True:
            candidate = out_dir / f"{stem} ({i}){ext}"
            if not candidate.exists():
                out_path = candidate
                break
            i += 1
    return out_path

def seconds_to_hms(s: float) -> str:
    s = max(0.0, float(s))
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = int(s % 60)
    if h:
        return f"{h:d}h {m:02d}m {sec:02d}s"
    if m:
        return f"{m:d}m {sec:02d}s"
    return f"{sec:d}s"

# -----------------------------
# Processor Adaptors
# -----------------------------
@dataclass
class FileResult:
    file: str
    output_file: Optional[str]
    file_type: str
    success: bool
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    timing_sec: float = 0.0
    stats: Dict[str, Any] = field(default_factory=dict)  # coverage, counts, etc.

    def to_json(self) -> Dict[str, Any]:
        return asdict(self)

def _try_import(module_name: str):
    with contextlib.suppress(Exception):
        return importlib.import_module(module_name)
    return None

def _call_if_exists(mod, func_names: List[str], *args, **kwargs):
    for fname in func_names:
        if hasattr(mod, fname):
            fn = getattr(mod, fname)
            try:
                return True, fn(*args, **kwargs)
            except TypeError:
                # Retry with fewer args (compat variants)
                with contextlib.suppress(Exception):
                    return True, fn(*args[:2])  # (input, output)
                with contextlib.suppress(Exception):
                    return True, fn(*args[:2], kwargs.get("config"))
            except Exception as e:
                raise
    return False, None

def _run_subprocess(script: str, argv_variants: List[List[str]], logger: logging.Logger) -> Tuple[bool, Optional[str]]:
    """
    Try several CLI flag layouts for broad compatibility. The first that returns 0 wins.
    Return (success, captured_json_path_or_none)
    """
    for argv in argv_variants:
        try:
            cmd = [sys.executable, script] + argv
            logger.debug("Trying subprocess: %s", " ".join(shlex.quote(a) for a in cmd))
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if proc.returncode == 0:
                # Try to detect if the script printed a JSON line with a report path or inline JSON.
                out = proc.stdout.strip()
                # Heuristic: if stdout is valid JSON, return it
                with contextlib.suppress(Exception):
                    _ = json.loads(out)
                    return True, out
                # Else, success but no JSON
                return True, None
            else:
                logger.debug("Subprocess failed (code=%s). stderr:\n%s", proc.returncode, proc.stderr)
        except FileNotFoundError:
            logger.debug("Subprocess script not found: %s", script)
        except Exception as e:
            logger.debug("Subprocess error for %s: %s", script, e)
    return False, None

class PPTXAdapter:
    def __init__(self, cfg: Dict[str, Any], logger: logging.Logger):
        self.cfg = cfg
        self.logger = logger
        self.mod = _try_import("pptx_alt_processor") or _try_import("pptx_processor")

    def process(self, input_path: Path, output_path: Path) -> FileResult:
        start = time.time()
        out_json = None
        try:
            if self.mod:
                found, result = _call_if_exists(
                    self.mod,
                    ["process_file", "process_pptx"],
                    str(input_path),
                    str(output_path),
                    self.cfg,
                    logger=self.logger,
                )
                if found:
                    # If result looks like a dict, use it.
                    if isinstance(result, dict):
                        stats = result.get("stats") or {}
                    else:
                        stats = {}
                    return FileResult(
                        file=str(input_path),
                        output_file=str(output_path),
                        file_type="pptx",
                        success=True,
                        stats=stats,
                        timing_sec=time.time() - start,
                    )
            # Fallback to CLI execution
            argv_variants = [
                ["--input", str(input_path), "--output", str(output_path), "--config", "config.yaml"],
                ["-i", str(input_path), "-o", str(output_path), "-c", "config.yaml"],
                [str(input_path), str(output_path)],
            ]
            ok, out_json = _run_subprocess("pptx_alt_processor.py", argv_variants, self.logger)
            if not ok:
                # Try alternative filename
                ok, out_json = _run_subprocess("pptx_processor.py", argv_variants, self.logger)
            if ok:
                stats = {}
                with contextlib.suppress(Exception):
                    data = json.loads(out_json)  # inline JSON report
                    stats = data.get("stats") or {}
                return FileResult(
                    file=str(input_path), output_file=str(output_path), file_type="pptx",
                    success=True, stats=stats, timing_sec=time.time() - start
                )
            raise RuntimeError("No callable interface or working CLI detected for PPTX processor.")
        except Exception as e:
            return FileResult(
                file=str(input_path), output_file=str(output_path), file_type="pptx",
                success=False, error=f"{e}", timing_sec=time.time() - start
            )

class DOCXAdapter:
    def __init__(self, cfg: Dict[str, Any], logger: logging.Logger):
        self.cfg = cfg
        self.logger = logger
        self.mod = _try_import("docx_processor")

    def process(self, input_path: Path, output_path: Path) -> FileResult:
        start = time.time()
        try:
            if self.mod:
                found, result = _call_if_exists(
                    self.mod,
                    ["process_file", "process_docx"],
                    str(input_path),
                    str(output_path),
                    self.cfg,
                    logger=self.logger,
                )
                if found:
                    stats = {}
                    if isinstance(result, dict):
                        stats = result.get("stats") or result
                    return FileResult(
                        file=str(input_path),
                        output_file=str(output_path),
                        file_type="docx",
                        success=True,
                        stats=stats,
                        timing_sec=time.time() - start,
                    )
            # Fallback to CLI
            argv_variants = [
                ["--input", str(input_path), "--output", str(output_path), "--config", "config.yaml"],
                ["-i", str(input_path), "-o", str(output_path), "-c", "config.yaml"],
                [str(input_path), str(output_path)],
            ]
            ok, out_json = _run_subprocess("docx_processor.py", argv_variants, self.logger)
            if ok:
                stats = {}
                with contextlib.suppress(Exception):
                    data = json.loads(out_json)
                    stats = data.get("stats") or {}
                return FileResult(
                    file=str(input_path), output_file=str(output_path), file_type="docx",
                    success=True, stats=stats, timing_sec=time.time() - start
                )
            raise RuntimeError("No callable interface or working CLI detected for DOCX processor.")
        except Exception as e:
            return FileResult(
                file=str(input_path), output_file=str(output_path), file_type="docx",
                success=False, error=f"{e}", timing_sec=time.time() - start
            )

# -----------------------------
# Batch engine
# -----------------------------
@dataclass
class BatchSummary:
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    by_type: Dict[str, Dict[str, int]] = field(default_factory=lambda: {"pptx": {"total":0,"succeeded":0,"failed":0}, "docx":{"total":0,"succeeded":0,"failed":0}})
    duration_sec: float = 0.0

def process_one(infile: Path, input_root: Path, output_root: Path, adapters: Dict[str, Any], skip_existing: bool, logger: logging.Logger) -> FileResult:
    file_type = infile.suffix.lower().lstrip(".")
    out_path = rel_output_path(infile, input_root, output_root)

    # Optionally skip if output already exists
    if skip_existing and out_path.exists():
        return FileResult(
            file=str(infile), output_file=str(out_path), file_type=file_type,
            success=True, warnings=["skipped_existing"], stats={"skipped": True}, timing_sec=0.0
        )

    adapter = adapters.get(file_type)
    if adapter is None:
        return FileResult(file=str(infile), output_file=None, file_type=file_type, success=False, error="Unsupported type")

    # Ensure out directories exist
    out_path.parent.mkdir(parents=True, exist_ok=True)

    result = adapter.process(infile, out_path)
    return result

def format_progress(done: int, total: int, start_ts: float) -> str:
    now = time.time()
    elapsed = now - start_ts
    speed = (done / elapsed) if elapsed > 0 else 0.0  # files/sec
    eta = (total - done) / speed if speed > 0 else 0.0
    return f"{done}/{total} | elapsed {seconds_to_hms(elapsed)} | ETA {seconds_to_hms(eta)} | {speed*60:.1f} files/min"

def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Unified batch processor for .pptx and .docx")
    p.add_argument("--folder", "-f", required=True, help="Input folder to scan")
    p.add_argument("--output", "-o", required=True, help="Output folder for processed files")
    p.add_argument("--recursive", "-r", action="store_true", help="Recursively scan subfolders")
    p.add_argument("--config", "-c", default="config.yaml", help="Path to config.yaml")
    p.add_argument("--skip-existing", action="store_true", help="Skip files with existing outputs")
    p.add_argument("--workers", "-w", type=int, default=None, help="Max parallel workers (override config)")
    p.add_argument("--report", default=None, help="Path to write combined JSON report (default: <output>/batch_report.json)")
    p.add_argument("--dry-run", action="store_true", help="List files and exit without processing")
    args = p.parse_args(argv)

    input_root = Path(args.folder).expanduser().resolve()
    output_root = Path(args.output).expanduser().resolve()
    config_path = Path(args.config).expanduser().resolve()

    cfg = load_config(config_path)
    logger = setup_logging(output_root, cfg)
    logger.info("Batch start | input=%s | output=%s | recursive=%s", input_root, output_root, args.recursive)

    files = discover_files(input_root, recursive=args.recursive)
    files.sort()
    if not files:
        logger.warning("No supported files found in %s (recursive=%s).", input_root, args.recursive)
        return 0

    if args.dry_run:
        for f in files:
            print(f)
        print(f"Found {len(files)} files.")
        return 0

    # Workers from config (alt_text_handling.max_workers or pptx_processing.max_workers), then CLI override
    max_workers = (
        (cfg.get("alt_text_handling") or {}).get("max_workers")
        or ((cfg.get("pptx_processing") or {}).get("max_workers"))
        or 4
    )
    if args.workers:
        max_workers = args.workers
    logger.info("Using up to %s workers.", max_workers)

    # Prepare adapters
    adapters = {
        "pptx": PPTXAdapter(cfg, logger),
        "docx": DOCXAdapter(cfg, logger),
    }

    # Progress + execution
    start_ts = time.time()
    results: List[FileResult] = []
    total = len(files)
    done = 0

    # Thread pool parallelism
    with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        fut_to_path = {
            ex.submit(process_one, f, input_root, output_root, adapters, args.skip_existing, logger): f
            for f in files
        }
        for fut in cf.as_completed(fut_to_path):
            res: FileResult = fut.result()
            results.append(res)
            done += 1
            # Update progress line
            sys.stdout.write("\r" + format_progress(done, total, start_ts))
            sys.stdout.flush()
    sys.stdout.write("\n")

    # Build summary
    summary = BatchSummary()
    summary.total = total
    summary.duration_sec = time.time() - start_ts
    for r in results:
        kind = r.file_type
        summary.by_type.setdefault(kind, {"total":0,"succeeded":0,"failed":0})
        summary.by_type[kind]["total"] += 1
        if r.success:
            summary.succeeded += 1
            summary.by_type[kind]["succeeded"] += 1
        else:
            summary.failed += 1
            summary.by_type[kind]["failed"] += 1

    success_rate = (summary.succeeded / summary.total) if summary.total else 0.0
    logger.info("Batch finished: %d/%d succeeded (%.1f%%) in %s.",
                summary.succeeded, summary.total, success_rate*100, seconds_to_hms(summary.duration_sec))

    # Compute combined coverage if per-file stats are available
    total_elements = 0
    elements_with_alt = 0
    elements_decorative = 0
    for r in results:
        s = r.stats or {}
        total_elements += int(s.get("elements_total") or 0)
        elements_with_alt += int(s.get("elements_with_alt") or 0)
        elements_decorative += int(s.get("elements_decorative") or 0)
    combined_coverage = (elements_with_alt / total_elements) if total_elements else None

    # Generate unified JSON report
    report_path = Path(args.report) if args.report else (output_root / "batch_report.json")
    unified = {
        "batch": {
            "started_at": int(start_ts),
            "ended_at": int(time.time()),
            "duration_sec": summary.duration_sec,
            "input_folder": str(input_root),
            "output_folder": str(output_root),
            "recursive": args.recursive,
            "workers": max_workers,
            "version": "1.0.0",
        },
        "summary": {
            "combined_elements_total": total_elements,
            "combined_elements_with_alt": elements_with_alt,
            "combined_elements_decorative": elements_decorative,
            "combined_coverage": combined_coverage,
            "total_files": summary.total,
            "succeeded": summary.succeeded,
            "failed": summary.failed,
            "by_type": summary.by_type,
            "success_rate": success_rate,
        },
        "files": [r.to_json() for r in results],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(unified, f, indent=2)
    logger.info("Wrote unified report: %s", report_path)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
