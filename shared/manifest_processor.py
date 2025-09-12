#!/usr/bin/env python3
"""
Manifest-Based PPTX Processor
=============================

Processes PPTX files using the ALT manifest as single source of truth.
Handles extraction, generation with caching/idempotency, and provenance tracking.
"""

from __future__ import annotations
import logging
import time
from pathlib import Path
from typing import Dict, Any, Optional

from alt_manifest import AltManifest, AltManifestEntry, compute_image_hash, create_stable_key

logger = logging.getLogger(__name__)


class ManifestProcessor:
    """
    Processes PPTX files with manifest-based caching and single source of truth.
    
    Eliminates double LLaVA calls by checking:
    1. Preserve mode + existing ALT → use existing (no LLaVA)
    2. Cache hit by image hash → reuse previous generation  
    3. Only call LLaVA when no existing ALT and no cache hit
    """
    
    def __init__(self, config_manager, alt_generator):
        self.config = config_manager
        self.alt_generator = alt_generator
        
    def extract_and_generate(self, pptx_path: Path, manifest_path: Path, 
                            mode: str = "preserve", 
                            generate_thumbnails: bool = True) -> Dict[str, Any]:
        """
        Extract images from PPTX and generate/cache ALT text using manifest.
        
        Args:
            pptx_path: Path to PPTX file
            manifest_path: Path to manifest JSONL file
            mode: "preserve" or "replace" - how to handle existing ALT
            generate_thumbnails: Whether to generate thumbnail images
            
        Returns:
            Processing results with statistics
        """
        logger.info(f"Processing {pptx_path.name} with manifest (mode: {mode})")
        
        # Initialize manifest
        manifest = AltManifest(manifest_path)
        
        # Extract images and existing ALT text
        extraction_result = self._extract_images_to_manifest(
            pptx_path, manifest, generate_thumbnails
        )
        
        if not extraction_result['success']:
            return extraction_result
        
        # Generate missing ALT text with caching
        generation_result = self._generate_missing_alt_text(
            manifest, mode
        )
        
        # Save manifest
        manifest.save()

        if logger.isEnabledFor(logging.DEBUG):
            entries = manifest.get_all_entries()
            key_sample = [e.key for e in entries[:5]]
            logger.debug("First 5 manifest entry keys: %s", key_sample)

        # Combine results
        stats = manifest.get_statistics()
        
        result = {
            'success': True,
            'manifest_path': str(manifest_path),
            'extraction': extraction_result,
            'generation': generation_result,
            'statistics': stats,
            'total_entries': stats['total_entries'],
            'llava_calls_made': stats['llava_calls_made'],
            'with_suggested_alt': stats['with_suggested_alt']
        }
        
        logger.info(f"Manifest processing complete: {stats['total_entries']} entries, "
                   f"{stats['llava_calls_made']} LLaVA calls, "
                   f"{stats['with_suggested_alt']} with suggested ALT")
        
        return result
    
    def _extract_images_to_manifest(self, pptx_path: Path, manifest: AltManifest,
                                   generate_thumbnails: bool) -> Dict[str, Any]:
        """Extract images from PPTX and populate manifest entries."""
        logger.info("Extracting images and existing ALT text from PPTX")
        
        try:
            from pptx import Presentation
            from pptx.enum.shapes import MSO_SHAPE_TYPE
            from PIL import Image
            import io
            
            prs = Presentation(str(pptx_path))
            
            entries_created = 0
            thumbnails_generated = 0
            extraction_errors = []
            
            for slide_idx, slide in enumerate(prs.slides):
                # Get slide text for context
                slide_text = self._extract_slide_text(slide)
                slide_notes = self._extract_slide_notes(slide)
                
                image_count_on_slide = 0
                
                for shape_idx, shape in enumerate(slide.shapes):
                    try:
                        # Classify shape type and group membership
                        shape_type, is_group_child = manifest.classify_shape_type(shape, MSO_SHAPE_TYPE)
                        
                        # Get shape ID
                        shape_id = getattr(shape, 'shape_id', shape_idx)
                        
                        # Extract existing ALT text from PPTX (all shapes can have ALT text)
                        current_alt = self._extract_current_alt_text(shape)
                        
                        # Generate hash - for pictures use image data, for others use shape properties
                        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                            # Handle pictures with actual image data
                            if not hasattr(shape, 'image') or not shape.image:
                                continue
                            image_data = shape.image.blob
                            if not image_data:
                                continue
                            image_hash = compute_image_hash(image_data)
                            width_px = shape.image.size[0] if shape.image.size else 0
                            height_px = shape.image.size[1] if shape.image.size else 0
                        else:
                            # Handle non-picture shapes (lines, text boxes, etc.)
                            shape_properties = f"{shape_type}_{shape_id}_{slide_idx}"
                            if hasattr(shape, 'width') and hasattr(shape, 'height'):
                                width_px = int(shape.width.emu // 914400) if shape.width else 0  # Convert to pixels
                                height_px = int(shape.height.emu // 914400) if shape.height else 0
                                shape_properties += f"_{width_px}x{height_px}"
                            else:
                                width_px = height_px = 0
                            image_hash = compute_image_hash(shape_properties.encode('utf-8'))
                        
                        # Create stable key
                        key = create_stable_key(slide_idx, shape_id, image_hash)
                        
                        # Check if we already have this entry
                        existing_entry = manifest.get_entry(key)
                        if existing_entry:
                            logger.debug(f"Entry already exists for {key}, updating context")
                            # Update contextual information but preserve ALT decisions
                            existing_entry.slide_text = slide_text
                            existing_entry.slide_notes = slide_notes
                            if not existing_entry.existing_alt and current_alt:
                                existing_entry.existing_alt = current_alt
                                existing_entry.current_alt = current_alt  # Legacy sync
                            manifest.add_entry(existing_entry)
                            continue
                        
                        image_count_on_slide += 1
                        
                        # Create new manifest entry
                        entry = manifest.create_entry_from_shape(
                            key=key,
                            image_hash=image_hash,
                            slide_idx=slide_idx,
                            image_number=entries_created + 1,
                            current_alt=current_alt,
                            shape_type=shape_type,
                            is_group_child=is_group_child,
                            slide_text=slide_text,
                            slide_notes=slide_notes,
                            width_px=width_px,
                            height_px=height_px
                        )
                        
                        # Generate thumbnail only for picture shapes
                        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE and generate_thumbnails:
                            thumbnail_path = self._generate_thumbnail(
                                image_data, pptx_path, key
                            )
                            if thumbnail_path:
                                entry.thumbnail_path = str(thumbnail_path)
                                thumbnails_generated += 1
                        
                        manifest.add_entry(entry)
                        entries_created += 1
                        
                    except Exception as e:
                        error_msg = f"Error extracting shape at slide {slide_idx}, shape {shape_idx}: {e}"
                        logger.warning(error_msg)
                        extraction_errors.append(error_msg)
            
            logger.info(f"Extracted {entries_created} images, generated {thumbnails_generated} thumbnails")
            
            return {
                'success': True,
                'entries_created': entries_created,
                'thumbnails_generated': thumbnails_generated,
                'extraction_errors': extraction_errors
            }
            
        except Exception as e:
            logger.error(f"Image extraction failed: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'entries_created': 0
            }
    
    def _extract_current_alt_text(self, shape) -> str:
        """Extract current ALT text from PPTX shape."""
        try:
            # Try multiple methods to get ALT text
            alt_text = ""
            
            # Method 1: Direct alternative_text property
            try:
                alt_text = getattr(shape, 'alternative_text', '') or ''
            except:
                pass
            
            # Method 2: XML cNvPr element (more reliable)
            if not alt_text and hasattr(shape, '_element'):
                try:
                    pic_element = shape._element
                    nvpicpr = pic_element.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}cNvPr')
                    if nvpicpr is not None:
                        alt_text = nvpicpr.get('descr', '') or nvpicpr.get('title', '')
                except:
                    pass
            
            # Method 3: Title property fallback  
            if not alt_text:
                try:
                    alt_text = getattr(shape, 'title', '') or ''
                except:
                    pass
            
            return alt_text.strip()
            
        except Exception as e:
            logger.debug(f"Could not extract ALT text: {e}")
            return ""
    
    def _extract_slide_text(self, slide) -> str:
        """Extract text content from slide for context."""
        text_parts = []
        try:
            for shape in slide.shapes:
                if hasattr(shape, 'text') and shape.text.strip():
                    text_parts.append(shape.text.strip())
        except Exception as e:
            logger.debug(f"Could not extract slide text: {e}")
        
        return ' '.join(text_parts)[:500]  # Limit length
    
    def _extract_slide_notes(self, slide) -> str:
        """Extract slide notes for context."""
        try:
            if hasattr(slide, 'notes_slide') and slide.notes_slide:
                notes_text = ""
                for shape in slide.notes_slide.shapes:
                    if hasattr(shape, 'text') and shape.text.strip():
                        notes_text += shape.text.strip() + " "
                return notes_text.strip()[:300]  # Limit length
        except Exception as e:
            logger.debug(f"Could not extract slide notes: {e}")
        
        return ""
    
    def _generate_thumbnail(self, image_data: bytes, pptx_path: Path, key: str) -> Optional[Path]:
        """Generate thumbnail image for DOCX review."""
        try:
            from PIL import Image
            import io
            
            # Create thumbnails directory
            thumbs_dir = pptx_path.parent / f".{pptx_path.stem}_thumbs"
            thumbs_dir.mkdir(exist_ok=True)
            
            thumbnail_path = thumbs_dir / f"{key}.jpg"
            
            # Generate thumbnail
            img = Image.open(io.BytesIO(image_data))
            img.thumbnail((200, 200), Image.Resampling.LANCZOS)
            img.save(thumbnail_path, 'JPEG', quality=85)
            
            return thumbnail_path
            
        except Exception as e:
            logger.debug(f"Could not generate thumbnail for {key}: {e}")
            return None
    
    def _generate_missing_alt_text(self, manifest: AltManifest, mode: str) -> Dict[str, Any]:
        """Generate ALT text for entries that need it, using caching and idempotency."""
        logger.info(f"Generating missing ALT text (mode: {mode})")
        
        entries_needing_generation = []
        preserved_count = 0
        cached_count = 0
        
        # Check each entry to see if generation is needed
        for entry in manifest.get_all_entries():
            should_generate, cached_alt = manifest.should_generate_alt(
                entry.key, entry.image_hash, entry.current_alt, mode
            )
            
            if not should_generate:
                # Use existing or cached ALT
                if cached_alt:
                    if entry.current_alt.strip() and mode == "preserve":
                        # Preserve existing
                        manifest.record_generation(
                            entry, entry.current_alt, "existing", False
                        )
                        preserved_count += 1
                        manifest.log_decision(entry.key, mode, "current", "preserve mode with existing ALT")
                    else:
                        # Use cached
                        manifest.record_generation(
                            entry, cached_alt, "cached", False
                        )
                        cached_count += 1
                        manifest.log_decision(entry.key, mode, "cached", "reused from cache")
            else:
                entries_needing_generation.append(entry)
        
        logger.info(f"Found {len(entries_needing_generation)} entries needing generation, "
                   f"{preserved_count} preserved, {cached_count} cached")
        
        # Generate ALT text for entries that need it
        generation_errors = []
        generated_count = 0
        
        for entry in entries_needing_generation:
            try:
                start_time = time.time()
                
                # Check if this shape type should have ALT text generated via LLaVA
                if manifest.should_generate_for_shape_type(entry.shape_type):
                    # Generate ALT text using LLaVA with thumbnail
                    if entry.thumbnail_path and Path(entry.thumbnail_path).exists():
                        alt_text = self.alt_generator.generate_alt_text(
                            entry.thumbnail_path,
                            manifest=manifest,
                            entry_key=entry.key
                        )
                        
                        if alt_text and alt_text.strip():
                            generated_count += 1
                            logger.debug(f"Generated ALT for {entry.key}: {alt_text[:50]}...")
                        else:
                            error_msg = f"Empty ALT text generated for {entry.key}"
                            generation_errors.append(error_msg)
                            logger.warning(error_msg)
                    else:
                        logger.warning(f"No thumbnail available for {entry.key}, skipping LLaVA generation")
                        continue
                else:
                    # Use shape fallback for non-picture elements
                    fallback_alt = manifest.get_shape_fallback_alt(
                        entry.shape_type,
                        entry.is_group_child,
                        entry.width_px,
                        entry.height_px
                    )
                    
                    # Normalize the fallback text
                    normalized_alt, was_truncated = manifest.normalize_alt_text(fallback_alt)
                    
                    # Update entry with fallback ALT
                    entry.llm_raw = fallback_alt
                    entry.final_alt = normalized_alt
                    entry.truncated_flag = was_truncated
                    entry.llava_called = False
                    entry.decision_reason = "shape_fallback"
                    entry.source = "shape_fallback"
                    
                    # Update legacy fields for compatibility
                    entry.suggested_alt = normalized_alt
                    
                    manifest.add_entry(entry)
                    generated_count += 1
                    
                    logger.debug(f"Applied shape fallback for {entry.key}: {normalized_alt}")
                    
                duration_ms = int((time.time() - start_time) * 1000)
                manifest.log_decision(
                    entry.key, 
                    mode, 
                    entry.final_alt,
                    f"{'LLaVA' if entry.llava_called else 'shape_fallback'} in {duration_ms}ms"
                )
                    
            except Exception as e:
                error_msg = f"Generation failed for {entry.key}: {e}"
                generation_errors.append(error_msg)
                logger.warning(error_msg)
        
        return {
            'success': True,
            'generated_count': generated_count,
            'preserved_count': preserved_count,
            'cached_count': cached_count,
            'error_count': len(generation_errors),
            'errors': generation_errors[:10]  # Limit error list
        }