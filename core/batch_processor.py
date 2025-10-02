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

# Import path validation and file locking modules
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.path_validator import sanitize_input_path, validate_output_path, SecurityError, is_safe_path
from shared.file_lock_manager import FileLock, LockError

# -----------------------------
# Config loading (config_manager -> yaml fallback)
# -----------------------------
def load_config(config_path: Path) -> Dict[str, Any]:
    for name in ("config_manager", "shared.config_manager"):
        with contextlib.suppress(Exception):
            cm = importlib.import_module(name)
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
        fh = logging.FileHandler(output_dir / "batch_processor.txt", encoding="utf-8")
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

def discover_files(root: Path, recursive: bool, logger: logging.Logger) -> List[Path]:
    """
    Discover supported files in root directory.
    Validates each discovered file to ensure it's within safe directories.
    """
    def _is_real(path: Path) -> bool:
        name = path.name
        # Skip Office lock files and macOS dotfiles
        if name.startswith("~$") or name.startswith("._"):
            return False
        return path.is_file() and is_supported(path)

    discovered = []
    if recursive:
        candidates = [p for p in root.rglob("*") if _is_real(p)]
    else:
        candidates = [p for p in root.glob("*") if _is_real(p)]

    # Validate each discovered file
    for path in candidates:
        if is_safe_path(path):
            discovered.append(path)
        else:
            logger.warning(f"Skipping file outside allowed directories: {path.name}")

    return discovered

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

def _repo_root() -> Path:
    # project root is the parent of 'core'
    return Path(__file__).resolve().parents[1]

def _subproc_env() -> dict:
    env = os.environ.copy()
    root = _repo_root()
    # Ensure Python can import core/ and shared/
    extra = os.pathsep.join([str(root), str(root / "core"), str(root / "shared")])
    env["PYTHONPATH"] = (extra + os.pathsep + env.get("PYTHONPATH", "")) if env.get("PYTHONPATH") else extra
    return env

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
            proc = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                cwd=_repo_root(), env=_subproc_env()
            )
            if proc.returncode == 0:
                out = proc.stdout.strip()
                with contextlib.suppress(Exception):
                    _ = json.loads(out)
                    return True, out
                return True, None
            else:
                logger.debug("Subprocess failed (code=%s) for %s.\nSTDERR:\n%s", proc.returncode, script, proc.stderr)
        except FileNotFoundError:
            logger.debug("Subprocess script not found: %s", script)
        except Exception as e:
            logger.debug("Subprocess error for %s: %s", script, e)
    return False, None

def _run_module_subprocess(module_name: str, argv_variants: List[List[str]], logger: logging.Logger) -> Tuple[bool, Optional[str]]:
    """
    Try to run a module as a CLI: python -m <module> <argv>.
    Returns (success, captured_json_or_none).
    """
    for argv in argv_variants:
        try:
            cmd = [sys.executable, "-m", module_name] + argv
            logger.debug("Trying module subprocess: %s", " ".join(shlex.quote(a) for a in cmd))
            proc = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                cwd=_repo_root(), env=_subproc_env()
            )
            if proc.returncode == 0:
                out = proc.stdout.strip()
                with contextlib.suppress(Exception):
                    _ = json.loads(out)
                    return True, out
                return True, None
            else:
                logger.debug("Module subprocess failed (code=%s) for %s.\nSTDERR:\n%s", proc.returncode, module_name, proc.stderr)
        except Exception as e:
            logger.debug("Module subprocess error for %s: %s", module_name, e)
    return False, None

def _module_candidates_pptx():
    # Prefer alt processor if present, then the general one
    return ("core.pptx_alt_processor", "pptx_alt_processor",
            "core.pptx_processor", "pptx_processor")

def _expected_pptx_outputs(input_path: Path, output_path: Path, cfg: dict) -> List[Path]:
    """
    Build a small set of plausible locations the PPTX processor could write to.
    - output_path (file-level mirror that batcher passed down)
    - output_path.parent / input_filename (folder-level output, same name)
    - config-level output folder + mirrored path
    """
    outs = []
    # exact mirror file path
    outs.append(output_path)
    # same name inside the intended output folder
    outs.append(output_path.parent / input_path.name)

    # config-defined output folder (if processor ignores our --output)
    cfg_out = (cfg.get("paths") or {}).get("output_folder")
    if cfg_out:
        cfg_out_dir = Path(cfg_out)
        if not cfg_out_dir.is_absolute():
            cfg_out_dir = (_repo_root() / cfg_out).resolve()
        outs.append(cfg_out_dir / input_path.name)

    return outs

def _search_by_stem(root: Path, stem: str, since_ts: float) -> Optional[Path]:
    """Last-resort: find a fresh .pptx anywhere under output root that shares the same stem"""
    try:
        for p in root.rglob("*.pptx"):
            if p.stem == stem and p.stat().st_mtime >= since_ts - 0.5:
                return p
    except Exception:
        pass
    return None

def _verify_pptx_result(input_path: Path, output_path: Path, cfg: dict, start_ts: float) -> Tuple[bool, Optional[Path]]:
    """
    Accept success only if an expected artifact exists and is fresh.
    """
    # 1) Expected explicit locations
    for candidate in _expected_pptx_outputs(input_path, output_path, cfg):
        if candidate.exists() and candidate.stat().st_mtime >= start_ts - 0.5:
            return True, candidate
    # 2) In-place modification?
    try:
        if input_path.exists() and input_path.stat().st_mtime >= start_ts - 0.5:
            return True, input_path
    except Exception:
        pass
    # 3) Anywhere under batch output root with same stem
    out_root = Path(cfg.get("__batch_output_root__", output_path.parent))
    hit = _search_by_stem(out_root, input_path.stem, start_ts)
    if hit:
        return True, hit
    return False, None

class PPTXAdapter:
    def __init__(self, cfg: Dict[str, Any], logger: logging.Logger):
        self.cfg = cfg
        self.logger = logger

        self.mod = None
        for name in _module_candidates_pptx():
            mod = _try_import(name)
            if mod:
                self.logger.debug("PPTXAdapter using import: %s", name)
                self.mod = mod
                break

    def process(self, input_path: Path, output_path: Path) -> FileResult:
        start = time.time()
        cfg = self.cfg
        try:
            # ---------- Tier 1: direct callable ----------
            if self.mod:
                # Try common function names first
                func_names = ["process_file", "process_pptx"]
                found, result = _call_if_exists(
                    self.mod, func_names,
                    str(input_path), str(output_path), cfg, logger=self.logger
                )
                if found:
                    ok, out_file = _verify_pptx_result(input_path, output_path, cfg, start)
                    if ok:
                        stats = {}
                        if isinstance(result, dict):
                            stats = result.get("stats") or result
                        return FileResult(
                            file=str(input_path),
                            output_file=str(out_file),
                            file_type="pptx",
                            success=True,
                            stats=stats,
                            timing_sec=time.time() - start,
                        )
                    else:
                        self.logger.debug("PPTXAdapter: callable returned but no fresh artifact; falling back to CLI.")

            # ---------- Tier 2a: module CLI with real command shapes ----------
            # Many PPTX CLIs expect a 'process' subcommand; try several variants.
            # Use a folder for --output in case the processor expects a directory, not a file path.
            config_path = str(Path(cfg.get("__config_path__", "config.yaml")).resolve())
            out_dir = str(output_path.parent)

            argv_variants = [
                # Most common in your stack: subcommand 'process'
                ["process", "--input", str(input_path), "--output", out_dir, "--config", config_path],
                ["process", "-i", str(input_path), "-o", out_dir, "-c", config_path],

                # Rely entirely on config paths (common & fast to type)
                ["process", str(input_path), "--config", config_path],
                ["--debug", "process", str(input_path), "--config", config_path],

                # Legacy / alternate arg names some forks used
                ["process", "--in", str(input_path), "--out", out_dir, "--config", config_path],
                ["--input", str(input_path), "--output", str(output_path), "--config", config_path],
                ["-i", str(input_path), "-o", str(output_path), "-c", config_path],
                [str(input_path), str(output_path)],
            ]

            for modname in _module_candidates_pptx():
                ok, out_json = _run_module_subprocess(modname, argv_variants, self.logger)
                if ok:
                    verified, out_file = _verify_pptx_result(input_path, output_path, cfg, start)
                    if verified:
                        stats = {}
                        with contextlib.suppress(Exception):
                            data = json.loads(out_json) if out_json else {}
                            stats = data.get("stats") or {}
                        return FileResult(
                            file=str(input_path),
                            output_file=str(out_file),
                            file_type="pptx",
                            success=True,
                            stats=stats,
                            timing_sec=time.time() - start,
                        )

            # ---------- Tier 2b: direct script path fallback ----------
            repo_root = Path(__file__).resolve().parents[1]
            script_candidates = [
                Path(__file__).resolve().parent / "pptx_alt_processor.py",
                Path(__file__).resolve().parent / "pptx_processor.py",
                repo_root / "core" / "pptx_alt_processor.py",
                repo_root / "core" / "pptx_processor.py",
            ]
            script_candidates = [p for p in script_candidates if p.exists()]

            for script in script_candidates:
                ok, out_json = _run_subprocess(str(script), argv_variants, self.logger)
                if ok:
                    verified, out_file = _verify_pptx_result(input_path, output_path, cfg, start)
                    if verified:
                        stats = {}
                        with contextlib.suppress(Exception):
                            data = json.loads(out_json) if out_json else {}
                            stats = data.get("stats") or {}
                        return FileResult(
                            file=str(input_path),
                            output_file=str(out_file),
                            file_type="pptx",
                            success=True,
                            stats=stats,
                            timing_sec=time.time() - start,
                        )

            raise RuntimeError("No callable interface or working CLI detected for PPTX processor (or no fresh output artifact).")
        except Exception as e:
            return FileResult(
                file=str(input_path),
                output_file=str(output_path),
                file_type="pptx",
                success=False,
                error=f"{e}",
                timing_sec=time.time() - start,
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

def process_one(infile: Path, input_root: Path, output_root: Path, adapters: Dict[str, Any], skip_existing: bool, logger: logging.Logger, cfg: Dict[str, Any] = None) -> FileResult:
    file_type = infile.suffix.lower().lstrip(".")

    # Validate input file path (defense in depth)
    try:
        if not is_safe_path(infile):
            logger.error(f"Security violation: file outside allowed directories: {infile}")
            return FileResult(
                file=str(infile), output_file=None, file_type=file_type,
                success=False, error="Security: file outside allowed directories"
            )
    except Exception as e:
        logger.error(f"Path validation error for {infile}: {e}")
        return FileResult(
            file=str(infile), output_file=None, file_type=file_type,
            success=False, error=f"Path validation failed: {e}"
        )

    out_path = rel_output_path(infile, input_root, output_root)

    # Validate output path
    try:
        if not is_safe_path(out_path):
            logger.error(f"Security violation: output path outside allowed directories: {out_path}")
            return FileResult(
                file=str(infile), output_file=None, file_type=file_type,
                success=False, error="Security: output path outside allowed directories"
            )
    except Exception as e:
        logger.error(f"Output path validation error for {out_path}: {e}")
        return FileResult(
            file=str(infile), output_file=None, file_type=file_type,
            success=False, error=f"Output path validation failed: {e}"
        )

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

    # Get file locking configuration
    lock_config = (cfg or {}).get("file_locking", {}) if cfg else {}
    locking_enabled = lock_config.get("enabled", True)
    lock_timeout = lock_config.get("timeout_seconds", 30)

    # Process with file locking to prevent concurrent access corruption
    if locking_enabled:
        try:
            with FileLock(infile, timeout=lock_timeout) as lock:
                result = adapter.process(infile, out_path)
                return result
        except LockError as e:
            logger.warning(f"File locked, skipping: {infile.name}")
            return FileResult(
                file=str(infile),
                output_file=None,
                file_type=file_type,
                success=False,
                error=f"File locked by another process (timeout after {lock_timeout}s)",
                timing_sec=0.0
            )
    else:
        # Locking disabled, process directly
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

    # Validate input folder path
    try:
        input_root = sanitize_input_path(args.folder)
    except SecurityError as e:
        print(f"Security Error (input folder): {e}")
        return 1
    except (ValueError, Exception) as e:
        print(f"Invalid input folder: {e}")
        return 1

    # Validate output folder path
    try:
        output_root = validate_output_path(args.output, create_parents=True)
    except SecurityError as e:
        print(f"Security Error (output folder): {e}")
        return 1
    except (ValueError, Exception) as e:
        print(f"Invalid output folder: {e}")
        return 1

    # Validate config path
    try:
        config_path = sanitize_input_path(args.config)
        # If not absolute in original args, look for root-level config
        if not Path(args.config).is_absolute():
            candidate = Path(__file__).resolve().parents[1] / Path(args.config).name
            if candidate.exists():
                config_path = sanitize_input_path(str(candidate))
    except SecurityError as e:
        print(f"Security Error (config): {e}")
        return 1
    except (ValueError, Exception) as e:
        print(f"Invalid config path: {e}")
        return 1

    cfg = load_config(config_path)

    # Make paths discoverable to adapters
    cfg["__config_path__"] = str(config_path)
    cfg["__batch_output_root__"] = str(output_root)

    logger = setup_logging(output_root, cfg)
    logger.info("Batch start | input=%s | output=%s | recursive=%s", input_root, output_root, args.recursive)

    files = discover_files(input_root, recursive=args.recursive, logger=logger)
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
            ex.submit(process_one, f, input_root, output_root, adapters, args.skip_existing, logger, cfg): f
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
    if args.report:
        try:
            report_path = validate_output_path(args.report)
        except SecurityError as e:
            logger.error(f"Security Error (report path): {e}")
            return 1
        except (ValueError, Exception) as e:
            logger.error(f"Invalid report path: {e}")
            return 1
    else:
        report_path = output_root / "batch_report.json"

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
