#!/usr/bin/env python3
"""Sequential batch processing for PPTX files.

This module implements the minimal Phase 2B.1 batch workflow:
- Accepts a folder path or glob pattern
- Discovers ``.pptx`` files (recursively for folders)
- Processes files sequentially using the existing single-file processor
- Uses Phase 2A.1 path sanitization safeguards
"""

from __future__ import annotations

import glob
import logging
import os
import subprocess
import sys
import yaml
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Add project root for shared imports when executed directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.path_validator import SecurityError, sanitize_input_path
from shared.batch_queue import DONE_STATUSES, QueueStatus
from shared.file_fingerprint import file_fingerprint as get_file_fingerprint

logger = logging.getLogger(__name__)


def _find_item(queue: Any, file_path: Path) -> Optional[Any]:
    """Return queue item for file path (match by path string or resolve)."""
    path_str = str(file_path)
    try:
        resolved = file_path.resolve()
    except OSError:
        resolved = None
    for i in queue.items:
        p = getattr(i, "path", None)
        if p == path_str:
            return i
        if resolved and p:
            try:
                if Path(p).resolve() == resolved:
                    return i
            except OSError:
                pass
    return None


def _mark_started(queue: Any, item: Any) -> None:
    """Mark item as PROCESSING and save."""
    item.mark_started()
    if queue.manifest_path:
        queue.save()


def _record_failed(
    queue: Any,
    item: Any,
    error: str,
    file_path: Path,
    fp: str,
    provider_offline: bool,
) -> None:
    """Record FAILED and persist result metadata."""
    item.status = QueueStatus.FAILED
    item.completed_at = datetime.now().isoformat()
    item.error = error
    item.result = dict(item.result) if item.result else {}
    item.result["file_fingerprint"] = fp
    item.result["exit_code"] = -1
    item.result["error_summary"] = error
    item.result["provider_offline"] = provider_offline
    item.result["output_path"] = str(file_path)
    if queue.manifest_path:
        queue.save()


def _apply_result(
    queue: Any,
    item: Any,
    result: Dict[str, Any],
    file_path: Path,
    fp: str,
    provider_offline: bool,
) -> None:
    """Apply _process_single result to item and persist (COMPLETE, FAILED, TIMED_OUT)."""
    base = {
        "file_fingerprint": fp,
        "provider_offline": provider_offline,
        "output_path": str(file_path),
        "exit_code": result.get("returncode", 0),
        "error_summary": result.get("error", ""),
    }
    if result.get("timed_out"):
        queue.mark_timed_out(
            item,
            result.get("error", "Timed out"),
            result={**base, **result},
        )
        return
    if result.get("success"):
        queue.mark_complete(item, result={**base, **result})
        return
    # Subprocess failed: classify as FAILED (no LOCKED here; we did not do pre-check or we would have skipped)
    queue.mark_failed(item, result.get("error", "Unknown error"))
    if item.result is None:
        item.result = {}
    item.result.update(base)
    if queue.manifest_path:
        queue.save()


class PPTXBatchProcessor:
    """Simple, sequential batch processor for PPTX files."""

    def __init__(self, config_path: str | None = None, processor_path: Path | None = None):
        self.config_path = config_path
        self.processor_path = self._resolve_processor(processor_path)
        self._timeout = self._load_timeout()

    def discover_files(self, target: str) -> List[Path]:
        """Discover PPTX files from a folder or glob pattern.

        Args:
            target: Folder path, file path, or glob pattern.

        Returns:
            Sorted list of PPTX file paths.

        Raises:
            FileNotFoundError: If the target path does not exist.
            SecurityError: If path validation fails.
            ValueError: If a non-PPTX file is supplied directly.
        """
        if glob.has_magic(target):
            base_dir, pattern = self._split_glob(target)
            validated_base = sanitize_input_path(str(base_dir), allow_absolute=True)
            if not validated_base.exists():
                raise FileNotFoundError(f"Path not found: {validated_base}")
            discovered = validated_base.glob(pattern)
        else:
            validated_path = sanitize_input_path(target, allow_absolute=True)
            if not validated_path.exists():
                raise FileNotFoundError(f"Path not found: {validated_path}")

            if validated_path.is_dir():
                discovered = validated_path.rglob("*.pptx")
            else:
                if validated_path.suffix.lower() != ".pptx":
                    raise ValueError("Only .pptx files can be processed")
                discovered = [validated_path]

        files = [
            path
            for path in discovered
            if path.is_file() and path.suffix.lower() == ".pptx" and not path.name.startswith("~$")
        ]

        return sorted(files)

    def process_batch(
        self,
        files: Sequence[Path],
        manifest_path: Optional[Path] = None,
        input_root: Optional[Path] = None,
        run_dir: Optional[Path] = None,
    ) -> Dict[str, object]:
        """Process PPTX files sequentially, with optional checkpoint/resume via manifest.

        When manifest_path is set: load or create manifest, skip DONE+unchanged files,
        reprocess on fingerprint mismatch, retry TIMED_OUT/LOCKED/PENDING. Persist after
        each file. When manifest_path is None, behavior is unchanged (no manifest).
        When input_root and run_dir are set, per-file artifacts are written under
        run_dir/outputs/<relative_path>/ (artifact base passed to subprocess via env).
        """
        if manifest_path is None:
            return self._process_batch_no_manifest(files)

        # Resume/checkpoint path: use shared batch_manifest
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))
        from batch_manifest import BatchManifest  # noqa: E402

        manifest_path = Path(manifest_path)
        if manifest_path.exists():
            manifest = BatchManifest.load(manifest_path)
            manifest.queue.reset_processing_items()
            logger.info("Resumed batch from %s", manifest_path)
        else:
            manifest = BatchManifest.create_new(
                manifest_path.parent,
                files=list(files),
                manifest_path=manifest_path,
            )
            manifest.start()

        # Ensure all discovered files are in the queue
        manifest.add_files(list(files))

        total = len(files)
        results: Dict[str, Any] = {
            "total": total,
            "succeeded": 0,
            "failed": 0,
            "errors": [],
            "skipped": 0,
        }

        for index, file_path in enumerate(files, start=1):
            item = _find_item(manifest.queue, file_path)
            if item is None:
                continue
            fp_current = get_file_fingerprint(file_path)
            stored_fp = (item.result or {}).get("file_fingerprint", "")

            # DONE + fingerprint match → skip
            if item.status in DONE_STATUSES:
                if stored_fp and stored_fp == fp_current:
                    manifest_loc = getattr(manifest, "manifest_path", None)
                    manifest_hint = f" (manifest: {manifest_loc})" if manifest_loc else ""
                    print(
                        f"Skipping {index} of {total}: {file_path.name} "
                        f"(status={item.status.value}, unchanged){manifest_hint}"
                    )
                    logger.info(
                        "Skipping %s (status=%s, unchanged) manifest=%s",
                        file_path.name,
                        item.status.value,
                        str(manifest_loc) if manifest_loc else "n/a",
                    )
                    logger.debug(
                        "Fingerprint match for %s: current=%s stored=%s",
                        file_path.name,
                        fp_current,
                        stored_fp,
                    )
                    results["skipped"] += 1
                    continue
                # Fingerprint differs: reprocess
                item.status = QueueStatus.PENDING
                item.result = dict(item.result) if item.result else {}
                item.result["file_fingerprint"] = fp_current
                item.completed_at = None
                item.error = None
                item.started_at = None
                print(f"Input changed; reprocessing: {file_path.name}")
                logger.info("input changed; reprocessing %s", file_path.name)
                manifest.save()

            # Conservative lock: if lockfile exists, treat as LOCKED (no stale check)
            lock_file = file_path.parent / (file_path.name + ".lock")
            if lock_file.exists():
                manifest.queue.mark_locked(
                    item, "lock file present",
                    result={
                        "file_fingerprint": fp_current,
                        "provider_offline": False,
                        "output_path": str(file_path),
                    },
                )
                manifest.save()
                print(f"Skipping {index} of {total}: {file_path.name} (LOCKED)")
                logger.info("Skipping %s (LOCKED)", file_path.name)
                continue

            # Retryable or PENDING: process
            item.mark_started()
            manifest.save()

            artifact_base: Optional[Path] = None
            if input_root is not None and run_dir is not None:
                try:
                    file_path.resolve().relative_to(input_root.resolve())
                except ValueError:
                    logger.warning(
                        "File %s is not under input_root %s (symlink escape?); skipping artifact base",
                        file_path,
                        input_root,
                    )
                else:
                    rel = file_path.relative_to(input_root).parent
                    if str(rel) == ".":
                        rel = Path(".")
                    artifact_base = run_dir / "outputs" / rel

            print(f"Processing {index} of {total}: {file_path.name}")
            try:
                result = self._process_single(file_path, artifact_base=artifact_base)
            except Exception as exc:
                logger.error("Unexpected error for %s: %s", file_path, exc)
                _record_failed(manifest.queue, item, str(exc), file_path, fp_current, False)
                manifest.save()
                results["failed"] += 1
                results["errors"].append({"file": str(file_path), "error": str(exc)})
                continue

            _apply_result(manifest.queue, item, result, file_path, fp_current, False)
            manifest.save()
            if result.get("success"):
                results["succeeded"] += 1
            else:
                results["failed"] += 1
                results["errors"].append({
                    "file": str(file_path),
                    "error": result.get("error", "Unknown error"),
                })

        manifest.finish()
        return results

    def _process_batch_no_manifest(self, files: Sequence[Path]) -> Dict[str, object]:
        """Original process_batch behavior (no manifest)."""
        total = len(files)
        results: Dict[str, object] = {
            "total": total,
            "succeeded": 0,
            "failed": 0,
            "errors": [],
        }

        for index, file_path in enumerate(files, start=1):
            print(f"Processing {index} of {total}: {file_path.name}")
            try:
                result = self._process_single(file_path)
            except Exception as exc:
                logger.error("Unexpected error for %s: %s", file_path, exc)
                results["failed"] += 1
                results["errors"].append({"file": str(file_path), "error": str(exc)})
                continue

            if result.get("success"):
                results["succeeded"] += 1
            else:
                results["failed"] += 1
                results["errors"].append(
                    {"file": str(file_path), "error": result.get("error", "Unknown error")}
                )

        return results

    def _process_single(
        self, file_path: Path, artifact_base: Optional[Path] = None
    ) -> Dict[str, object]:
        """Process a single PPTX file using the existing processor.

        When artifact_base is set, subprocess receives VISUALTEXT_ARTIFACT_BASE_DIR so
        per-file artifacts are written under that directory. Set only for subprocess
        lifetime (env passed to run(), not os.environ).
        """
        validated_path = sanitize_input_path(str(file_path), allow_absolute=True)

        cmd = [
            sys.executable,
            str(self.processor_path),
            "process",
            str(validated_path),
        ]

        if self.config_path and self.config_path != "config.yaml":
            cmd.extend(["--config", self.config_path])

        env = os.environ.copy()
        if artifact_base is not None:
            env["VISUALTEXT_ARTIFACT_BASE_DIR"] = str(artifact_base)
        else:
            env.pop("VISUALTEXT_ARTIFACT_BASE_DIR", None)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            # Capture stdout/stderr from the TimeoutExpired exception if available
            # Note: TimeoutExpired.stdout/stderr are bytes even when text=True
            stdout = ""
            stderr = ""
            if exc.stdout:
                stdout = exc.stdout.decode("utf-8") if isinstance(exc.stdout, bytes) else str(exc.stdout)
            if exc.stderr:
                stderr = exc.stderr.decode("utf-8") if isinstance(exc.stderr, bytes) else str(exc.stderr)
            
            logger.error(
                "Subprocess timeout for file: %s (timeout: %d seconds)",
                file_path.name,
                self._timeout,
            )
            logger.error("Command: %s", " ".join(cmd))
            logger.error("stdout: %s", stdout if stdout else "(empty)")
            logger.error("stderr: %s", stderr if stderr else "(empty)")
            
            return {
                "success": False,
                "error": f"Processing timed out after {self._timeout} seconds",
                "stdout": stdout,
                "stderr": stderr,
                "returncode": -1,
                "timed_out": True,
            }
        except Exception as exc:
            logger.error(
                "Subprocess exception for file: %s: %s", file_path.name, exc
            )
            logger.error("Command: %s", " ".join(cmd))
            logger.error("Exception type: %s", type(exc).__name__)
            return {
                "success": False,
                "error": f"Subprocess exception: {str(exc)}",
                "stdout": "",
                "stderr": "",
                "returncode": -1,
                "timed_out": False,
            }

        if result.returncode == 0:
            return {
                "success": True,
                "output": result.stdout,
                "returncode": 0,
                "timed_out": False,
            }

        # Non-zero return code - log full output
        logger.error(
            "Subprocess failed for file: %s (returncode: %d)",
            file_path.name,
            result.returncode,
        )
        logger.error("Command: %s", " ".join(cmd))
        logger.error("stdout: %s", result.stdout if result.stdout else "(empty)")
        logger.error("stderr: %s", result.stderr if result.stderr else "(empty)")

        return {
            "success": False,
            "error": result.stderr or result.stdout or "Processing failed",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "timed_out": False,
        }

    @staticmethod
    def _split_glob(pattern: str) -> Tuple[Path, str]:
        """Separate a glob pattern into base directory and pattern."""
        pattern_path = Path(pattern)
        base_parts = []
        pattern_parts = []
        wildcard_found = False

        for part in pattern_path.parts:
            if glob.has_magic(part) or wildcard_found:
                wildcard_found = True
                pattern_parts.append(part)
            else:
                base_parts.append(part)

        base_dir = Path(*base_parts) if base_parts else Path(".")
        remaining_pattern = str(Path(*pattern_parts)) if pattern_parts else "*.pptx"
        return base_dir, remaining_pattern

    def _load_timeout(self) -> int:
        """Load timeout from config.yaml with fallback to default.

        Returns:
            Timeout in seconds (default: 300).
        """
        default_timeout = 300
        config_file = None

        # Determine config file path
        if self.config_path:
            config_file = Path(self.config_path)
        else:
            # Look for config.yaml in project root
            project_root = Path(__file__).resolve().parents[1]
            config_file = project_root / "config.yaml"

        if not config_file or not config_file.exists():
            logger.debug(
                "Config file not found, using default timeout: %d seconds",
                default_timeout,
            )
            return default_timeout

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            
            timeout = (
                config.get("batch_processing", {})
                .get("file_timeout_seconds", default_timeout)
            )
            
            if not isinstance(timeout, int) or timeout <= 0:
                logger.warning(
                    "Invalid timeout value in config, using default: %d seconds",
                    default_timeout,
                )
                return default_timeout
            
            logger.debug("Loaded timeout from config: %d seconds", timeout)
            return timeout
        except Exception as exc:
            logger.warning(
                "Error loading timeout from config (%s), using default: %d seconds",
                exc,
                default_timeout,
            )
            return default_timeout

    @staticmethod
    def _resolve_processor(custom_path: Path | None) -> Path:
        """Locate the single-file processor script."""
        if custom_path:
            resolved = custom_path
        else:
            resolved = Path(__file__).resolve().parents[1] / "pptx_alt_processor.py"

        if not resolved.exists():
            raise FileNotFoundError("Could not locate pptx_alt_processor.py")

        return resolved


__all__ = ["PPTXBatchProcessor"]
