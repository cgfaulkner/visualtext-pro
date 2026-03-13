#!/usr/bin/env python3
"""
Run folder and manifest path resolution for staged batch runs.

Resolves run_dir and manifest_path from CLI/config with explicit precedence:
resume_manifest > run_id > manifest_dir > new run (auto run_id).
"""

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RunFolderResult:
    """Result of resolve_run_folder_and_manifest."""

    run_dir: Optional[Path]
    manifest_path: Optional[Path]
    run_id: Optional[str]
    used_resume_manifest: bool


def resolve_run_folder_and_manifest(
    input_root: Path,
    staging_root: str,
    run_id: Optional[str] = None,
    resume_manifest: Optional[Path] = None,
    manifest_dir: Optional[Path] = None,
    force: bool = False,
) -> RunFolderResult:
    """
    Resolve run directory and manifest path for batch processing.

    Precedence: resume_manifest (absolute) > run_id > manifest_dir > new run.
    When force is True, returns (None, None, None, False).

    Args:
        input_root: Root input directory (for staged runs under it).
        staging_root: Name of staging dir under input_root (e.g. "staged_runs").
        run_id: Optional run id to resume or create under input_root/staging_root.
        resume_manifest: Optional absolute path to manifest (takes precedence).
        manifest_dir: Optional directory for manifest; run_dir = manifest_dir (rule A).
        force: If True, no manifest/run_dir (reprocess all).

    Returns:
        RunFolderResult with run_dir, manifest_path, run_id, used_resume_manifest.
    """
    if force:
        return RunFolderResult(
            run_dir=None,
            manifest_path=None,
            run_id=None,
            used_resume_manifest=False,
        )

    input_root = Path(input_root).resolve()
    if resume_manifest is not None:
        resume_manifest = Path(resume_manifest).resolve()
    if manifest_dir is not None:
        manifest_dir = Path(manifest_dir)

    # Precedence: resume_manifest > run_id > manifest_dir > new run
    if resume_manifest is not None:
        if run_id is not None:
            logger.warning(
                "resume_manifest overrides --run-id; using manifest at %s",
                resume_manifest,
            )
        manifest_path = resume_manifest
        run_dir = manifest_path.parent
        return RunFolderResult(
            run_dir=run_dir,
            manifest_path=manifest_path,
            run_id=run_dir.name,
            used_resume_manifest=True,
        )

    if run_id is not None:
        run_dir = input_root / staging_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = run_dir / "manifest.json"
        return RunFolderResult(
            run_dir=run_dir,
            manifest_path=manifest_path,
            run_id=run_id,
            used_resume_manifest=False,
        )

    if manifest_dir is not None:
        if manifest_dir.is_absolute():
            run_dir = manifest_dir.resolve()
        else:
            run_dir = (input_root / manifest_dir).resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = run_dir / "manifest.json"
        return RunFolderResult(
            run_dir=run_dir,
            manifest_path=manifest_path,
            run_id=run_dir.name,
            used_resume_manifest=False,
        )

    # New run: UTC run_id, collision suffix -1..-10, then random suffix escape hatch
    base_run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    for suffix in ["", "-1", "-2", "-3", "-4", "-5", "-6", "-7", "-8", "-9", "-10"]:
        candidate_id = base_run_id + suffix
        run_dir = input_root / staging_root / candidate_id
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
            manifest_path = run_dir / "manifest.json"
            return RunFolderResult(
                run_dir=run_dir,
                manifest_path=manifest_path,
                run_id=candidate_id,
                used_resume_manifest=False,
            )
        except FileExistsError:
            continue

    # Escape hatch: append short random suffix
    for _ in range(5):
        candidate_id = base_run_id + "-" + secrets.token_hex(4)
        run_dir = input_root / staging_root / candidate_id
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
            manifest_path = run_dir / "manifest.json"
            return RunFolderResult(
                run_dir=run_dir,
                manifest_path=manifest_path,
                run_id=candidate_id,
                used_resume_manifest=False,
            )
        except FileExistsError:
            continue

    raise RuntimeError(
        "Could not create unique run directory after 10 attempts and random-suffix escape hatch."
    )
