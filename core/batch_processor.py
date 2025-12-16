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
import subprocess
import sys
import yaml
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

# Add project root for shared imports when executed directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.path_validator import SecurityError, sanitize_input_path

logger = logging.getLogger(__name__)


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

    def process_batch(self, files: Sequence[Path]) -> Dict[str, object]:
        """Process PPTX files sequentially.

        Args:
            files: Iterable of PPTX file paths.

        Returns:
            Summary dictionary with counts and per-file errors.
        """
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
            except Exception as exc:  # Catch-all so one file does not stop the batch
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

    def _process_single(self, file_path: Path) -> Dict[str, object]:
        """Process a single PPTX file using the existing processor."""
        validated_path = sanitize_input_path(str(file_path), allow_absolute=True)

        cmd = [
            sys.executable,
            str(self.processor_path),
            "process",
            str(validated_path),
        ]

        if self.config_path and self.config_path != "config.yaml":
            cmd.extend(["--config", self.config_path])

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self._timeout
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
            }

        if result.returncode == 0:
            return {"success": True, "output": result.stdout}

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
