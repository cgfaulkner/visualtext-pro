#!/usr/bin/env python3
"""
Pipeline Artifacts Management
============================

Manages the structured data flow through the three-phase pipeline:
- Phase 1: Scan (visual_index + current_alt_by_key)
- Phase 2: Generate (generated_alt_by_key) 
- Phase 3: Resolve (final_alt_map)

This ensures clean separation of concerns and single source of truth.
"""

from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


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
    
    @classmethod
    def create_for_run(cls, pptx_path: Path, base_dir: Optional[Path] = None) -> RunArtifacts:
        """
        Create RunArtifacts structure for a new pipeline run.
        
        Args:
            pptx_path: Path to the PPTX file being processed
            base_dir: Optional base directory for artifacts (defaults to pptx_path.parent)
            
        Returns:
            RunArtifacts instance with all paths configured
        """
        import time
        
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
            final_alt_map_path=run_dir / "resolve" / "final_alt_map.json"
        )
    
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
    
    def cleanup(self, keep_finals: bool = True) -> None:
        """
        Clean up temporary artifacts.
        
        Args:
            keep_finals: If True, keep final_alt_map.json for future use
        """
        import shutil
        
        if not keep_finals:
            if self.run_dir.exists():
                shutil.rmtree(self.run_dir)
        else:
            # Keep only final artifacts
            finals_to_keep = [
                self.final_alt_map_path,
                self.visual_index_path  # Keep for DOCX generation
            ]
            
            for path in self.run_dir.rglob("*"):
                if path.is_file() and path not in finals_to_keep:
                    path.unlink()
            
            # Remove empty directories
            for path in self.run_dir.rglob("*"):
                if path.is_dir() and not any(path.iterdir()):
                    path.rmdir()