#!/usr/bin/env python3
"""
Pipeline Artifacts Management
============================

Manages the structured data flow through the three-phase pipeline:
- Phase 1: Scan (visual_index + current_alt_by_key)
- Phase 2: Generate (generated_alt_by_key)
- Phase 3: Resolve (final_alt_map)

This ensures clean separation of concerns and single source of truth.

Usage as Context Manager:
    with RunArtifacts.create_for_run(pptx_path) as artifacts:
        # Process phases
        # Automatic cleanup on exit
        pass
"""

from __future__ import annotations
import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


FinalAltRecord = Dict[str, Optional[str]]


def _coerce_text(value: Any) -> str:
    """Convert value to stripped string, returning empty string for falsy values."""
    if value is None:
        return ""
    return str(value).strip()


def _coerce_optional_text(value: Any) -> Optional[str]:
    """Convert value to stripped string, returning None when the result is empty."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_source(value: Any, default: str) -> str:
    """Coerce source identifiers to non-empty strings with a sensible default."""
    text = _coerce_text(value)
    return text or default


def normalize_final_alt_map(raw_map: Dict[str, Any]) -> Dict[str, FinalAltRecord]:
    """Normalize legacy and new final_alt_map payloads into the canonical structure."""
    if not isinstance(raw_map, dict):
        return {}

    normalized: Dict[str, FinalAltRecord] = {}

    for key, value in raw_map.items():
        if not isinstance(key, str):
            continue

        if isinstance(value, dict):
            existing_alt = _coerce_text(value.get('existing_alt'))
            generated_alt = _coerce_text(value.get('generated_alt'))
            final_alt = _coerce_optional_text(value.get('final_alt'))
            decision = _coerce_optional_text(value.get('decision'))

            normalized[key] = {
                'existing_alt': existing_alt,
                'generated_alt': generated_alt,
                'source_existing': _coerce_source(value.get('source_existing'), 'pptx'),
                'source_generated': _coerce_source(value.get('source_generated'), 'llava'),
                'final_alt': final_alt,
                'decision': decision,
            }
        else:
            generated_alt = _coerce_text(value)
            normalized[key] = {
                'existing_alt': '',
                'generated_alt': generated_alt,
                'source_existing': 'pptx',
                'source_generated': 'llava',
                'final_alt': generated_alt or None,
                'decision': None,
            }

    return normalized


@dataclass
class RunArtifacts:
    """
    Manages file paths and metadata for a single pipeline run.

    This provides the single source of truth for all pipeline artifacts,
    ensuring clean data flow between phases and consumers.

    Can be used as a context manager for automatic cleanup:
        with RunArtifacts.create_for_run(pptx_path) as artifacts:
            # Processing happens here
            pass
        # Automatic cleanup happens here
    """
    run_dir: Path
    session_id: str

    # Phase 1: Scan artifacts
    current_alt_by_key_path: Path       # scan/current_alt_by_key.json
    visual_index_path: Path             # scan/visual_index.json
    thumbs_dir: Path                    # thumbs/
    crops_dir: Path                     # crops/ (NEW: model input images)
    manifest_path: Path                 # manifest.json (NEW: single source of truth)

    # Phase 2: Generate artifacts
    generated_alt_by_key_path: Path     # generate/generated_alt_by_key.json

    # Phase 3: Resolve artifacts
    final_alt_map_path: Path            # resolve/final_alt_map.json

    # Cleanup control
    cleanup_on_exit: bool = field(default=True)
    _processing_succeeded: bool = field(default=False, init=False)
    
    @classmethod
    def create_for_run(cls, pptx_path: Path, base_dir: Optional[Path] = None,
                      cleanup_on_exit: bool = True) -> RunArtifacts:
        """
        Create RunArtifacts structure for a new pipeline run.

        Args:
            pptx_path: Path to the PPTX file being processed
            base_dir: Optional base directory for artifacts (defaults to pptx_path.parent)
            cleanup_on_exit: If True, cleanup artifacts when used as context manager

        Returns:
            RunArtifacts instance with all paths configured
        """
        if base_dir is None:
            base_dir = pptx_path.parent

        # Create session-specific directory
        session_id = f"{pptx_path.stem}_{int(time.time())}"
        run_dir = base_dir / f".alt_pipeline_{session_id}"

        # Ensure directories exist
        run_dir.mkdir(exist_ok=True)
        (run_dir / "scan").mkdir(exist_ok=True)
        (run_dir / "generate").mkdir(exist_ok=True)
        (run_dir / "resolve").mkdir(exist_ok=True)
        (run_dir / "thumbs").mkdir(exist_ok=True)
        (run_dir / "crops").mkdir(exist_ok=True)

        return cls(
            run_dir=run_dir,
            session_id=session_id,
            current_alt_by_key_path=run_dir / "scan" / "current_alt_by_key.json",
            visual_index_path=run_dir / "scan" / "visual_index.json",
            thumbs_dir=run_dir / "thumbs",
            crops_dir=run_dir / "crops",
            manifest_path=run_dir / "manifest.json",
            generated_alt_by_key_path=run_dir / "generate" / "generated_alt_by_key.json",
            final_alt_map_path=run_dir / "resolve" / "final_alt_map.json",
            cleanup_on_exit=cleanup_on_exit
        )

    def __enter__(self) -> 'RunArtifacts':
        """Enter context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager with automatic cleanup."""
        if self.cleanup_on_exit:
            # If exception occurred, don't keep finals
            keep_finals = (exc_type is None) and self._processing_succeeded
            try:
                self.cleanup(keep_finals=keep_finals)
            except Exception as e:
                logger.warning(f"Cleanup failed (non-fatal): {e}")
        return None

    def mark_success(self) -> None:
        """Mark processing as succeeded (keeps finals on cleanup)."""
        self._processing_succeeded = True
    
    def load_current_alt_by_key(self) -> Dict[str, str]:
        """Load current ALT text mappings from Phase 1."""
        if not self.current_alt_by_key_path.exists():
            return {}
        
        with open(self.current_alt_by_key_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def save_current_alt_by_key(self, data: Dict[str, str]) -> None:
        """Save current ALT text mappings from Phase 1."""
        with open(self.current_alt_by_key_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def load_visual_index(self) -> Dict[str, Any]:
        """Load visual index from Phase 1."""
        if not self.visual_index_path.exists():
            return {}
        
        with open(self.visual_index_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def save_visual_index(self, data: Dict[str, Any]) -> None:
        """Save visual index from Phase 1."""
        with open(self.visual_index_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def load_generated_alt_by_key(self) -> Dict[str, str]:
        """Load generated ALT text mappings from Phase 2."""
        if not self.generated_alt_by_key_path.exists():
            return {}
        
        with open(self.generated_alt_by_key_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def save_generated_alt_by_key(self, data: Dict[str, str]) -> None:
        """Save generated ALT text mappings from Phase 2."""
        with open(self.generated_alt_by_key_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def load_final_alt_map(self) -> Dict[str, FinalAltRecord]:
        """Load final resolved ALT text mappings from Phase 3."""
        if not self.final_alt_map_path.exists():
            return {}

        with open(self.final_alt_map_path, 'r', encoding='utf-8') as f:
            raw_map = json.load(f)

        return normalize_final_alt_map(raw_map)

    def save_final_alt_map(self, data: Dict[str, Any]) -> None:
        """Save final resolved ALT text mappings from Phase 3."""
        normalized = normalize_final_alt_map(data)

        with open(self.final_alt_map_path, 'w', encoding='utf-8') as f:
            json.dump(normalized, f, indent=2, ensure_ascii=False)
    
    def get_manifest_path(self) -> Path:
        """Get path to the single source of truth manifest file."""
        return self.manifest_path
    
    def cleanup(self, keep_finals: bool = True) -> Dict[str, Any]:
        """
        Clean up temporary artifacts.

        Args:
            keep_finals: If True, keep final_alt_map.json and visual_index.json for future use

        Returns:
            Dict with cleanup statistics: files_removed, dirs_removed, bytes_freed, errors
        """
        stats = {
            'files_removed': 0,
            'dirs_removed': 0,
            'bytes_freed': 0,
            'errors': []
        }

        if not self.run_dir.exists():
            logger.debug(f"Artifact directory doesn't exist, nothing to clean: {self.run_dir}")
            return stats

        try:
            if not keep_finals:
                # Complete cleanup - remove everything
                try:
                    # Calculate size before deletion
                    stats['bytes_freed'] = self._calculate_dir_size(self.run_dir)
                    shutil.rmtree(self.run_dir)
                    stats['dirs_removed'] = 1
                    logger.info(f"Cleaned up artifact directory: {self.run_dir} ({stats['bytes_freed']} bytes)")
                except Exception as e:
                    error_msg = f"Failed to remove artifact directory {self.run_dir}: {e}"
                    logger.error(error_msg)
                    stats['errors'].append(error_msg)
            else:
                # Selective cleanup - keep finals
                finals_to_keep = {
                    self.final_alt_map_path,
                    self.visual_index_path  # Keep for DOCX generation
                }

                # Remove files
                for path in list(self.run_dir.rglob("*")):
                    if path.is_file() and path not in finals_to_keep:
                        try:
                            size = path.stat().st_size
                            path.unlink()
                            stats['files_removed'] += 1
                            stats['bytes_freed'] += size
                        except Exception as e:
                            error_msg = f"Failed to remove file {path}: {e}"
                            logger.debug(error_msg)
                            stats['errors'].append(error_msg)

                # Remove empty directories (bottom-up)
                for path in sorted(self.run_dir.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                    if path.is_dir() and not any(path.iterdir()):
                        try:
                            path.rmdir()
                            stats['dirs_removed'] += 1
                        except Exception as e:
                            error_msg = f"Failed to remove directory {path}: {e}"
                            logger.debug(error_msg)
                            stats['errors'].append(error_msg)

                logger.info(f"Cleaned up artifacts (kept finals): {stats['files_removed']} files, "
                          f"{stats['bytes_freed']} bytes freed")

        except Exception as e:
            error_msg = f"Cleanup failed: {e}"
            logger.error(error_msg)
            stats['errors'].append(error_msg)

        return stats

    @staticmethod
    def _calculate_dir_size(path: Path) -> int:
        """Calculate total size of directory in bytes."""
        total = 0
        try:
            for item in path.rglob("*"):
                if item.is_file():
                    try:
                        total += item.stat().st_size
                    except:
                        pass
        except:
            pass
        return total

    @staticmethod
    def cleanup_old_artifacts(base_dir: Path, max_age_days: int = 7, dry_run: bool = False) -> Dict[str, Any]:
        """
        Clean up old .alt_pipeline_* directories.

        Args:
            base_dir: Base directory to search for artifact directories
            max_age_days: Maximum age in days before cleanup
            dry_run: If True, only report what would be cleaned, don't actually clean

        Returns:
            Dict with cleanup statistics: count, bytes_freed, directories
        """
        stats = {
            'count': 0,
            'bytes_freed': 0,
            'directories': [],
            'errors': []
        }

        if not base_dir.exists():
            return stats

        cutoff_time = time.time() - (max_age_days * 86400)  # 86400 seconds per day

        try:
            for path in base_dir.glob(".alt_pipeline_*"):
                if not path.is_dir():
                    continue

                try:
                    # Check modification time
                    mtime = path.stat().st_mtime
                    if mtime < cutoff_time:
                        size = RunArtifacts._calculate_dir_size(path)
                        age_days = (time.time() - mtime) / 86400

                        stats['directories'].append({
                            'path': str(path),
                            'age_days': round(age_days, 1),
                            'size_bytes': size
                        })

                        if not dry_run:
                            try:
                                shutil.rmtree(path)
                                stats['count'] += 1
                                stats['bytes_freed'] += size
                                logger.info(f"Removed old artifact directory: {path.name} "
                                          f"(age: {age_days:.1f} days, size: {size} bytes)")
                            except Exception as e:
                                error_msg = f"Failed to remove {path}: {e}"
                                logger.error(error_msg)
                                stats['errors'].append(error_msg)
                        else:
                            stats['count'] += 1
                            stats['bytes_freed'] += size

                except Exception as e:
                    error_msg = f"Error processing {path}: {e}"
                    logger.debug(error_msg)
                    stats['errors'].append(error_msg)

        except Exception as e:
            error_msg = f"Failed to scan for old artifacts: {e}"
            logger.error(error_msg)
            stats['errors'].append(error_msg)

        return stats