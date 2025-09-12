#!/usr/bin/env python3
"""
ALT Text Manifest - Single Source of Truth
==========================================

Manages the alt_manifest.jsonl file that serves as the single source of truth
for all ALT text decisions. This eliminates double LLaVA calls and ensures
consistency between PPTX injection and DOCX review generation.

Each row represents one visual element with complete traceability.
"""

from __future__ import annotations
import hashlib
import json
import logging
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Literal, Iterator
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class AltManifestEntry:
    """Single entry in the ALT text manifest representing one visual element."""
    
    # Identity
    key: str                    # slide_{idx}_shapeid_{id}_hash_{hash}
    image_hash: str            # SHA-256 of normalized image bytes
    
    # ALT text states
    current_alt: str           # ALT that existed in PPTX before generation (may be "")
    suggested_alt: str         # The LLaVA result or preserved current ALT
    
    # Provenance
    source: Literal["existing", "generated", "cached"]  # Where suggested_alt came from
    llava_called: bool         # Whether LLaVA was actually invoked for this entry
    
    # Generation metadata (when source != "existing")
    prompt_type: Optional[str] = None
    provider: Optional[str] = None
    duration_ms: Optional[int] = None
    
    # Context for traceability
    slide_idx: int = 0
    slide_number: int = 1
    image_number: int = 1
    slide_text: str = ""
    slide_notes: str = ""
    
    # Processing metadata
    timestamp: str = ""
    thumbnail_path: Optional[str] = None
    width_px: int = 0
    height_px: int = 0
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


class AltManifest:
    """
    Manages the ALT text manifest for a single PPTX processing run.
    
    Provides caching, idempotency, and single source of truth for all
    ALT text decisions across PPTX injection and DOCX review.
    """
    
    def __init__(self, manifest_path: Path):
        self.manifest_path = manifest_path
        self._entries: Dict[str, AltManifestEntry] = {}
        self._hash_to_key: Dict[str, str] = {}  # For cache lookups by image_hash
        self._load_existing()
    
    def _load_existing(self):
        """Load existing manifest entries from JSONL file."""
        if not self.manifest_path.exists():
            logger.info(f"Creating new manifest: {self.manifest_path}")
            return
        
        logger.info(f"Loading existing manifest: {self.manifest_path}")
        try:
            with open(self.manifest_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                        
                    try:
                        data = json.loads(line)
                        entry = AltManifestEntry(**data)
                        self._entries[entry.key] = entry
                        self._hash_to_key[entry.image_hash] = entry.key
                    except Exception as e:
                        logger.warning(f"Skipping invalid manifest line {line_num}: {e}")
                        
            logger.info(f"Loaded {len(self._entries)} existing manifest entries")
            
        except Exception as e:
            logger.error(f"Failed to load manifest: {e}")
            # Continue with empty manifest
    
    def save(self):
        """Save all entries to JSONL file."""
        logger.info(f"Saving manifest with {len(self._entries)} entries")
        
        # Ensure parent directory exists
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(self.manifest_path, 'w', encoding='utf-8') as f:
                for entry in self._entries.values():
                    json.dump(asdict(entry), f, ensure_ascii=False)
                    f.write('\n')
                    
            logger.info(f"Manifest saved: {self.manifest_path}")
            
        except Exception as e:
            logger.error(f"Failed to save manifest: {e}")
            raise
    
    def get_entry(self, key: str) -> Optional[AltManifestEntry]:
        """Get manifest entry by key."""
        return self._entries.get(key)
    
    def get_by_hash(self, image_hash: str) -> Optional[AltManifestEntry]:
        """Get manifest entry by image hash (for cache lookups)."""
        key = self._hash_to_key.get(image_hash)
        return self._entries.get(key) if key else None
    
    def add_entry(self, entry: AltManifestEntry) -> None:
        """Add or update a manifest entry."""
        self._entries[entry.key] = entry
        self._hash_to_key[entry.image_hash] = entry.key
        logger.debug(f"Added manifest entry: {entry.key} (source: {entry.source})")
    
    def create_entry_from_shape(self, key: str, image_hash: str, slide_idx: int, 
                               image_number: int, current_alt: str = "",
                               **kwargs) -> AltManifestEntry:
        """
        Create a manifest entry from shape extraction data.
        
        Does not add to manifest - use add_entry() for that.
        """
        return AltManifestEntry(
            key=key,
            image_hash=image_hash,
            current_alt=current_alt.strip(),
            suggested_alt="",  # Will be filled by generation or preservation logic
            source="existing" if current_alt.strip() else "generated",  # Initial assumption
            llava_called=False,
            slide_idx=slide_idx,
            slide_number=slide_idx + 1,
            image_number=image_number,
            **kwargs
        )
    
    def should_generate_alt(self, key: str, image_hash: str, current_alt: str,
                           mode: str = "preserve") -> tuple[bool, Optional[str]]:
        """
        Determine if ALT text should be generated and return cached result if available.
        
        Returns:
            (should_call_llava, cached_suggested_alt)
        """
        current_cleaned = current_alt.strip()
        
        # Check preserve mode first
        if mode == "preserve" and current_cleaned:
            logger.debug(f"Preserve mode: using existing ALT for {key}")
            return False, current_cleaned
        
        # Check if we have this exact entry already
        existing_entry = self.get_entry(key)
        if existing_entry and existing_entry.suggested_alt:
            logger.debug(f"Found existing entry for {key}: {existing_entry.source}")
            return False, existing_entry.suggested_alt
        
        # Check cache by image hash
        cached_entry = self.get_by_hash(image_hash)
        if cached_entry and cached_entry.suggested_alt:
            logger.debug(f"Found cached entry by hash for {key}: {cached_entry.source}")
            return False, cached_entry.suggested_alt
        
        # Need to generate
        logger.debug(f"Need to generate ALT for {key}")
        return True, None
    
    def record_generation(self, entry: AltManifestEntry, suggested_alt: str,
                         source: str, llava_called: bool, duration_ms: Optional[int] = None,
                         provider: Optional[str] = None, prompt_type: Optional[str] = None):
        """Record the result of ALT text generation or preservation."""
        entry.suggested_alt = suggested_alt.strip()
        entry.source = source
        entry.llava_called = llava_called
        
        if duration_ms is not None:
            entry.duration_ms = duration_ms
        if provider:
            entry.provider = provider  
        if prompt_type:
            entry.prompt_type = prompt_type
            
        self.add_entry(entry)
    
    def get_all_entries(self) -> List[AltManifestEntry]:
        """Get all manifest entries as a list."""
        return list(self._entries.values())
    
    def get_entries_by_slide(self) -> Dict[int, List[AltManifestEntry]]:
        """Get entries grouped by slide index."""
        by_slide = {}
        for entry in self._entries.values():
            slide_idx = entry.slide_idx
            if slide_idx not in by_slide:
                by_slide[slide_idx] = []
            by_slide[slide_idx].append(entry)
        return by_slide
    
    def get_statistics(self) -> Dict[str, int]:
        """Get statistics about the manifest contents."""
        stats = {
            'total_entries': len(self._entries),
            'with_current_alt': 0,
            'with_suggested_alt': 0,
            'source_existing': 0,
            'source_generated': 0,
            'source_cached': 0,
            'llava_calls_made': 0
        }
        
        for entry in self._entries.values():
            if entry.current_alt:
                stats['with_current_alt'] += 1
            if entry.suggested_alt:
                stats['with_suggested_alt'] += 1
                
            stats[f'source_{entry.source}'] += 1
            
            if entry.llava_called:
                stats['llava_calls_made'] += 1
        
        return stats
    
    def log_decision(self, key: str, mode: str, alt_used: str, reasoning: str = ""):
        """Log a structured decision for traceability."""
        entry = self.get_entry(key)
        if not entry:
            logger.warning(f"No manifest entry found for decision logging: {key}")
            return
            
        decision = {
            'key': key,
            'image_hash': entry.image_hash,
            'mode': mode,
            'alt_used': alt_used,
            'source': entry.source,
            'llava_called': entry.llava_called,
            'reasoning': reasoning
        }
        
        logger.info(f"DECISION: {json.dumps(decision)}")


def compute_image_hash(image_data: bytes) -> str:
    """
    Compute normalized hash of image data.
    
    For now, use raw bytes. Could add normalization (RGBA→RGB, scaling)
    if needed for better cache hits across different extractions.
    """
    return hashlib.sha256(image_data).hexdigest()


def create_stable_key(slide_idx: int, shape_id: int, image_hash: str) -> str:
    """Create stable key for image identification."""
    return f"slide_{slide_idx}_shapeid_{shape_id}_hash_{image_hash[:8]}"