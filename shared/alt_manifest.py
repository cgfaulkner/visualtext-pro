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

# Manifest schema version for tracking compatibility
MANIFEST_SCHEMA_VERSION = "2.0.0"


@dataclass
class AltManifestEntry:
    """Single entry in the ALT text manifest representing one visual element."""
    
    # Identity and classification (NEW SCHEMA 2.0)
    instance_key: str = ""      # slide_index + shape_id (unique per presentation instance)
    content_key: str = ""       # hash of rendered crop or original blob (for content-based matching)
    key: str = ""               # slide_{idx}_shapeid_{id}_hash_{hash} (legacy compatibility)
    image_hash: str = ""        # SHA-256 of normalized image bytes (legacy compatibility)
    slide_no: int = 0          # 1-based slide number for display
    shape_type: str = "PICTURE"  # PICTURE, AUTO_SHAPE, TEXT_BOX, LINE, TABLE, GROUP, etc.
    is_group_child: bool = False  # True if this element is part of a grouped object
    bbox: Dict[str, float] = None  # Bounding box coordinates {"left": 0, "top": 0, "width": 0, "height": 0}
    format: str = ""            # File format: png/jpg/wmf/emf/svg/shape
    
    # ALT text states  
    had_existing_alt: bool = False      # True if ALT existed in original PPTX
    existing_alt: str = ""              # Original ALT from PPTX (preserved for reference)
    llava_called: bool = False          # Whether LLaVA was actually invoked (NEW SCHEMA 2.0)
    llm_called: bool = False            # Whether LLaVA was actually invoked (legacy compatibility)
    llm_raw: str = ""                   # Raw LLaVA output before normalization
    final_alt: str = ""                 # Final ALT text used (sentence-complete, length-capped)
    decision_reason: str = ""           # preserved|generated|shape_fallback|decorative
    include_reason: str = ""            # Why this element was included for processing
    exclude_reason: str = ""            # Why this element was excluded from processing
    truncated_flag: bool = False        # True if llm_raw was truncated to create final_alt
    
    # File paths (NEW SCHEMA 2.0)
    thumb_path: str = ""                # Path to display thumbnail (for DOCX)
    crop_path: str = ""                 # Path to model input image (cropped from slide)
    
    # Rasterizer information (NEW SCHEMA 2.0)
    rasterizer_info: Dict[str, any] = None  # {"engine": "slide_render|native", "dpi": 150, "status": "success|error"}
    
    # Provenance (legacy compatibility)
    current_alt: str = ""               # Alias for existing_alt
    suggested_alt: str = ""             # Alias for final_alt  
    source: Literal["existing", "generated", "cached", "shape_fallback"] = "existing"
    
    # Generation metadata
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
        
        # Initialize dict fields
        if self.bbox is None:
            self.bbox = {"left": 0, "top": 0, "width": 0, "height": 0}
        if self.rasterizer_info is None:
            self.rasterizer_info = {"engine": "", "dpi": 0, "status": ""}
        
        # Maintain synchronization between new and legacy fields
        self.slide_no = self.slide_number
        
        # Sync LLaVA call tracking
        if self.llava_called:
            self.llm_called = self.llava_called
        elif self.llm_called:
            self.llava_called = self.llm_called
        
        # Sync ALT text fields for backward compatibility
        if not self.current_alt and self.existing_alt:
            self.current_alt = self.existing_alt
        elif not self.existing_alt and self.current_alt:
            self.existing_alt = self.current_alt
            
        if not self.suggested_alt and self.final_alt:
            self.suggested_alt = self.final_alt
        elif not self.final_alt and self.suggested_alt:
            self.final_alt = self.suggested_alt
            
        # Set had_existing_alt flag
        if self.existing_alt.strip():
            self.had_existing_alt = True
            
        # Generate legacy key from instance_key if not present
        if self.instance_key and not self.key:
            self.key = self.instance_key


class AltManifest:
    """
    Manages the ALT text manifest for a single PPTX processing run.
    
    Provides caching, idempotency, and single source of truth for all
    ALT text decisions across PPTX injection and DOCX review.
    """
    
    def __init__(self, manifest_path: Path):
        self.manifest_path = manifest_path
        self.schema_version = MANIFEST_SCHEMA_VERSION
        self._entries: Dict[str, AltManifestEntry] = {}
        self._hash_to_key: Dict[str, str] = {}  # For cache lookups by image_hash
        self._content_to_key: Dict[str, str] = {}  # For cache lookups by content_key
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
                        
                        # Handle schema version header
                        if data.get('_type') == 'manifest_header':
                            self.schema_version = data.get('_manifest_schema_version', '1.0.0')
                            logger.info(f"Found manifest schema version: {self.schema_version}")
                            continue
                        
                        entry = AltManifestEntry(**data)
                        # Use appropriate key for indexing
                        lookup_key = entry.instance_key if entry.instance_key else entry.key
                        self._entries[lookup_key] = entry
                        
                        # Update lookup indices
                        if entry.image_hash:
                            self._hash_to_key[entry.image_hash] = lookup_key
                        if entry.content_key:
                            self._content_to_key[entry.content_key] = lookup_key
                    except Exception as e:
                        logger.warning(f"Skipping invalid manifest line {line_num}: {e}")
                        
            logger.info(f"Loaded {len(self._entries)} existing manifest entries")
            
        except Exception as e:
            logger.error(f"Failed to load manifest: {e}")
            # Continue with empty manifest
    
    def save(self):
        """Save all entries to JSONL file."""
        logger.info(f"Saving manifest with {len(self._entries)} entries (schema v{self.schema_version})")
        
        # Ensure parent directory exists
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(self.manifest_path, 'w', encoding='utf-8') as f:
                # Write schema version header as first line
                schema_header = {"_manifest_schema_version": self.schema_version, "_type": "manifest_header"}
                json.dump(schema_header, f, ensure_ascii=False)
                f.write('\n')
                
                # Write all entries
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
    
    def get_by_content_key(self, content_key: str) -> Optional[AltManifestEntry]:
        """Get manifest entry by content key (for cache lookups)."""
        key = self._content_to_key.get(content_key)
        return self._entries.get(key) if key else None
    
    def add_entry(self, entry: AltManifestEntry) -> None:
        """Add or update a manifest entry."""
        # Use instance_key if available, fallback to legacy key
        lookup_key = entry.instance_key if entry.instance_key else entry.key
        self._entries[lookup_key] = entry
        
        # Update lookup indices
        if entry.image_hash:
            self._hash_to_key[entry.image_hash] = lookup_key
        if entry.content_key:
            self._content_to_key[entry.content_key] = lookup_key
            
        logger.debug(f"Added manifest entry: {lookup_key} (source: {entry.source})")
    
    def create_entry_from_shape(self, key: str, image_hash: str, slide_idx: int, 
                               image_number: int, current_alt: str = "",
                               shape_type: str = "PICTURE", is_group_child: bool = False,
                               **kwargs) -> AltManifestEntry:
        """
        Create a manifest entry from shape extraction data.
        
        Does not add to manifest - use add_entry() for that.
        """
        current_cleaned = current_alt.strip()
        
        return AltManifestEntry(
            key=key,
            image_hash=image_hash,
            slide_no=slide_idx + 1,
            shape_type=shape_type,
            is_group_child=is_group_child,
            had_existing_alt=bool(current_cleaned),
            existing_alt=current_cleaned,
            current_alt=current_cleaned,  # Legacy compatibility
            suggested_alt="",  # Will be filled by generation or preservation logic
            final_alt="",      # Will be filled by generation or preservation logic
            source="existing" if current_cleaned else "generated",  # Initial assumption
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
    
    def classify_shape_type(self, shape, MSO_SHAPE_TYPE) -> tuple[str, bool]:
        """
        Classify a shape and determine if it's a group child.
        
        Returns:
            Tuple of (shape_type_str, is_group_child)
        """
        shape_type_map = {
            MSO_SHAPE_TYPE.PICTURE: "PICTURE",
            MSO_SHAPE_TYPE.AUTO_SHAPE: "AUTO_SHAPE", 
            MSO_SHAPE_TYPE.TEXT_BOX: "TEXT_BOX",
            MSO_SHAPE_TYPE.LINE: "LINE",
            MSO_SHAPE_TYPE.CONNECTOR: "CONNECTOR",
            MSO_SHAPE_TYPE.TABLE: "TABLE",
            MSO_SHAPE_TYPE.GROUP: "GROUP",
            MSO_SHAPE_TYPE.CHART: "CHART",
            MSO_SHAPE_TYPE.MEDIA: "MEDIA"
        }
        
        # Determine shape type
        shape_type = shape_type_map.get(shape.shape_type, f"UNKNOWN_{shape.shape_type}")
        
        # Check if this is a group child (simplified - would need more complex logic in real implementation)
        is_group_child = False
        try:
            # This is a simplified check - in reality you'd need to traverse the shape hierarchy
            if hasattr(shape, 'part') and hasattr(shape.part, 'element'):
                # Could check XML structure here to determine group membership
                pass
        except:
            pass
        
        return shape_type, is_group_child
    
    def get_statistics(self) -> Dict[str, int]:
        """Get statistics about the manifest contents."""
        stats = {
            'total_entries': len(self._entries),
            'with_current_alt': 0,
            'with_suggested_alt': 0,
            'source_existing': 0,
            'source_generated': 0,
            'source_cached': 0,
            'source_shape_fallback': 0,  # New source type for shape fallbacks
            'llava_calls_made': 0
        }
        
        for entry in self._entries.values():
            if entry.current_alt:
                stats['with_current_alt'] += 1
            if entry.suggested_alt:
                stats['with_suggested_alt'] += 1
            
            # Handle all possible source types dynamically
            source_key = f'source_{entry.source}'
            if source_key not in stats:
                stats[source_key] = 0
            stats[source_key] += 1
            
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
    
    def normalize_alt_text(self, raw_text: str, max_chars: int = 320) -> tuple[str, bool]:
        """
        Normalize ALT text with sentence-safe truncation.
        
        Args:
            raw_text: Raw LLaVA output or input text
            max_chars: Maximum character limit (default 320)
            
        Returns:
            Tuple of (normalized_text, was_truncated)
        """
        if not raw_text or not raw_text.strip():
            return "", False
        
        # Clean up the text
        text = raw_text.strip()
        text = ' '.join(text.split())  # Normalize whitespace
        
        # If already short enough, just ensure proper punctuation
        if len(text) <= max_chars:
            return self._ensure_terminal_punctuation(text), False
        
        # Need to truncate - find the best place to cut
        truncated = False
        
        # Look for sentence endings within the limit
        sentence_endings = ['.', '!', '?']
        best_cut = 0
        
        for i in range(max_chars, 0, -1):
            if i < len(text) and text[i-1] in sentence_endings:
                # Found a sentence ending within limit
                best_cut = i
                break
        
        # If no sentence ending found, look for other break points
        if best_cut == 0:
            # Look for clause breaks (semicolon, comma)
            for i in range(max_chars, max(0, max_chars - 50), -1):
                if i < len(text) and text[i-1] in [';', ',']:
                    best_cut = i
                    break
        
        # If still no good break point, cut at last space before limit
        if best_cut == 0:
            for i in range(max_chars, max(0, max_chars - 20), -1):
                if i < len(text) and text[i-1] == ' ':
                    best_cut = i
                    break
        
        # Final fallback - hard cut at limit
        if best_cut == 0:
            best_cut = max_chars
        
        # Truncate and clean up
        result = text[:best_cut].strip()
        if result.endswith(','):
            result = result[:-1].strip()
        
        truncated = len(result) < len(text)
        
        return self._ensure_terminal_punctuation(result), truncated
    
    def _ensure_terminal_punctuation(self, text: str) -> str:
        """Ensure text ends with proper punctuation."""
        if not text:
            return ""
        
        text = text.strip()
        if not text:
            return ""
        
        # If already ends with punctuation, return as-is
        if text[-1] in '.!?':
            return text
        
        # Add period for declarative sentences
        return text + "."
    
    def classify_shape_type(self, shape, shape_type_enum=None) -> tuple[str, bool]:
        """
        Classify shape type and determine if it's part of a group.
        
        Args:
            shape: PowerPoint shape object
            shape_type_enum: MSO_SHAPE_TYPE enum for classification
            
        Returns:
            Tuple of (shape_type_string, is_group_child)
        """
        if not shape_type_enum:
            try:
                from pptx.enum.shapes import MSO_SHAPE_TYPE
                shape_type_enum = MSO_SHAPE_TYPE
            except ImportError:
                logger.warning("Could not import MSO_SHAPE_TYPE, using fallback classification")
                return "UNKNOWN", False
        
        # Determine basic shape type
        shape_type = "UNKNOWN"
        is_group_child = False
        
        try:
            if shape.shape_type == shape_type_enum.PICTURE:
                shape_type = "PICTURE"
            elif shape.shape_type == shape_type_enum.AUTO_SHAPE:
                shape_type = "AUTO_SHAPE"
            elif shape.shape_type == shape_type_enum.TEXT_BOX:
                shape_type = "TEXT_BOX"
            elif shape.shape_type == shape_type_enum.LINE:
                shape_type = "LINE"
            elif shape.shape_type == shape_type_enum.TABLE:
                shape_type = "TABLE"
            elif shape.shape_type == shape_type_enum.GROUP:
                shape_type = "GROUP"
            elif shape.shape_type == shape_type_enum.CONNECTOR:
                shape_type = "CONNECTOR"
            else:
                shape_type = f"SHAPE_{shape.shape_type}"
        except Exception as e:
            logger.debug(f"Could not classify shape type: {e}")
        
        # Check if part of a group (simplified check)
        try:
            if hasattr(shape, '_element') and shape._element is not None:
                parent = shape._element.getparent()
                if parent is not None and 'grpSp' in parent.tag:
                    is_group_child = True
        except Exception as e:
            logger.debug(f"Could not check group membership: {e}")
        
        return shape_type, is_group_child
    
    def should_generate_for_shape_type(self, shape_type: str) -> bool:
        """
        Determine if a shape type should have ALT text generated.
        
        Args:
            shape_type: Shape type string (PICTURE, AUTO_SHAPE, etc.)
            
        Returns:
            True if ALT text should be generated, False for fallback text
        """
        # Only generate ALT text for actual images
        generatable_types = {"PICTURE"}
        
        return shape_type in generatable_types
    
    def get_shape_fallback_alt(self, shape_type: str, is_group_child: bool = False,
                              width_px: int = 0, height_px: int = 0) -> str:
        """
        Generate appropriate fallback ALT text for non-picture shapes.
        
        Args:
            shape_type: Shape type string
            is_group_child: Whether shape is part of a group
            width_px: Width in pixels
            height_px: Height in pixels
            
        Returns:
            Descriptive ALT text for the shape
        """
        if is_group_child:
            prefix = "Part of a grouped element: "
        else:
            prefix = ""
        
        # Generate size info if available
        size_info = ""
        if width_px > 0 and height_px > 0:
            size_info = f" ({width_px}×{height_px}px)"
        
        # Generate description based on shape type
        if shape_type == "TEXT_BOX":
            return f"{prefix}Text box{size_info}."
        elif shape_type == "AUTO_SHAPE":
            return f"{prefix}PowerPoint shape{size_info}."
        elif shape_type == "LINE":
            if width_px > 0 and height_px > 0:
                if width_px > height_px * 3:
                    return f"{prefix}Horizontal line{size_info}."
                elif height_px > width_px * 3:
                    return f"{prefix}Vertical line{size_info}."
                else:
                    return f"{prefix}Diagonal line{size_info}."
            return f"{prefix}Line element{size_info}."
        elif shape_type == "CONNECTOR":
            return f"{prefix}Connector line{size_info}."
        elif shape_type == "TABLE":
            return f"{prefix}Table{size_info}."
        elif shape_type == "GROUP":
            return f"{prefix}Grouped elements{size_info}."
        else:
            return f"{prefix}PowerPoint shape element{size_info}."


def compute_image_hash(image_data: bytes) -> str:
    """
    Compute normalized hash of image data.
    
    For now, use raw bytes. Could add normalization (RGBA→RGB, scaling)
    if needed for better cache hits across different extractions.
    """
    return hashlib.sha256(image_data).hexdigest()


def create_stable_key(slide_idx: int, shape_id: int, image_hash: str) -> str:
    """Create stable key for image identification (legacy compatibility)."""
    return f"slide_{slide_idx}_shapeid_{shape_id}_hash_{image_hash[:8]}"

def create_instance_key(slide_idx: int, shape_id: int) -> str:
    """Create instance key for shape identification (NEW SCHEMA 2.0)."""
    return f"slide_{slide_idx}_shape_{shape_id}"

def create_content_key(content_bytes: bytes) -> str:
    """Create content key from rendered crop or original blob bytes (NEW SCHEMA 2.0)."""
    return hashlib.sha256(content_bytes).hexdigest()

def parse_min_shape_area(area_str: str, slide_width: int = 720, slide_height: int = 540) -> int:
    """
    Parse minimum shape area from CLI string format.
    
    Args:
        area_str: Area specification like "1%" or "100px" 
        slide_width: Slide width in points (default: 720 = 10 inches at 72 DPI)
        slide_height: Slide height in points (default: 540 = 7.5 inches at 72 DPI)
        
    Returns:
        Minimum area in square points
    """
    if area_str.endswith('%'):
        # Percentage of slide area
        percentage = float(area_str[:-1])
        slide_area = slide_width * slide_height
        return int(slide_area * percentage / 100)
    elif area_str.endswith('px'):
        # Direct pixel area (assuming 72 DPI: 1 point = 1 pixel)
        return int(area_str[:-2])
    else:
        # Assume it's already in points
        return int(area_str)