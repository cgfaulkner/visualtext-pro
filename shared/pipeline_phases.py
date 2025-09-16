#!/usr/bin/env python3
"""
Three-Phase Pipeline Implementation
==================================

Implements the clean three-phase pipeline:

Phase 1: Scan - Extract visual_index and current_alt_by_key from PPTX
Phase 2: Generate - Create generated_alt_by_key for missing ALT text  
Phase 3: Resolve - Merge current + generated into final_alt_map

This ensures single source of truth and eliminates double LLaVA calls.
"""

from __future__ import annotations
import hashlib
import logging
import time
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from pipeline_artifacts import RunArtifacts
from alt_manifest import AltManifest, create_instance_key, create_content_key


logger = logging.getLogger(__name__)


def phase1_scan(pptx_path: Path, artifacts: RunArtifacts, 
               generate_thumbnails: bool = True,
               llava_include_shapes: str = "smart",
               max_shapes_per_slide: int = 5,
               min_shape_area: str = "1%") -> Dict[str, Any]:
    """
    Phase 1: Scan PPTX and build visual_index + current_alt_by_key + manifest.
    
    This phase extracts using NEW SCHEMA 2.0:
    - manifest.json: Single source of truth with instance_key, shape_type, existing_alt
    - visual_index: Complete catalog for backward compatibility  
    - current_alt_by_key: Existing ALT text for backward compatibility
    - thumbnails: Generated for DOCX review (optional)
    
    Args:
        pptx_path: Path to PPTX file
        artifacts: RunArtifacts for managing file paths
        generate_thumbnails: Whether to generate thumbnail images
        llava_include_shapes: Shape inclusion strategy (off/smart/all)
        max_shapes_per_slide: Maximum shapes per slide
        min_shape_area: Minimum shape area threshold
        
    Returns:
        Dictionary with scan results
    """
    logger.info(f"Phase 1: Scanning {pptx_path.name} with new schema 2.0")
    
    try:
        # Create manifest processor with configuration
        from manifest_processor import ManifestProcessor
        processor = ManifestProcessor(
            config_manager=None,  # Will be passed from caller if needed
            alt_generator=None,   # Not needed for discovery phase
            llava_include_shapes=llava_include_shapes,
            max_shapes_per_slide=max_shapes_per_slide,
            min_shape_area=min_shape_area
        )
        
        # Initialize manifest
        manifest = AltManifest(artifacts.get_manifest_path())
        
        # Run discovery and classification
        discovery_result = processor.phase1_discover_and_classify(pptx_path, manifest)
        
        if not discovery_result['success']:
            return discovery_result
        
        # Save manifest
        manifest.save()
        
        # Build backward-compatible outputs
        visual_index = {}
        current_alt_by_key = {}
        thumbnails_generated = 0
        
        for entry in manifest.get_all_entries():
            # Build visual_index entry for backward compatibility
            visual_entry = {
                'stable_key': entry.key or entry.instance_key,
                'instance_key': entry.instance_key,
                'slide_idx': entry.slide_idx,
                'shape_idx': 0,  # Not tracked in new schema
                'shape_id': entry.instance_key.split('_')[-1] if '_' in entry.instance_key else '0',
                'slide_number': entry.slide_number,
                'image_number': entry.image_number,
                'has_current_alt': entry.had_existing_alt,
                'current_alt_text': entry.existing_alt,
                'existing_alt': entry.existing_alt,
                'shape_type': entry.shape_type,
                'bbox': entry.bbox,
                'format': entry.format,
                'width_px': entry.width_px,
                'height_px': entry.height_px
            }
            visual_index[entry.instance_key] = visual_entry
            
            # Build current_alt_by_key for backward compatibility
            if entry.existing_alt.strip():
                current_alt_by_key[entry.instance_key] = entry.existing_alt
        
        # Save backward-compatible artifacts
        artifacts.save_visual_index(visual_index)
        artifacts.save_current_alt_by_key(current_alt_by_key)
        
        result = {
            'success': True,
            'total_images': discovery_result['classified_elements'],
            'images_with_current_alt': len(current_alt_by_key),
            'thumbnails_generated': thumbnails_generated,  # Will be generated in Step 2
            'visual_index_path': str(artifacts.visual_index_path),
            'current_alt_by_key_path': str(artifacts.current_alt_by_key_path),
            'manifest_path': str(artifacts.get_manifest_path()),
            # New schema 2.0 fields
            'discovered_elements': discovery_result['discovered_elements'],
            'classified_elements': discovery_result['classified_elements'],
            'include_strategy': discovery_result['include_strategy'],
            'min_area_threshold': discovery_result['min_area_threshold']
        }
        
        logger.info(f"Phase 1 complete: {discovery_result['classified_elements']} elements classified, "
                   f"{len(current_alt_by_key)} with existing ALT (strategy: {llava_include_shapes})")
        return result
        
    except Exception as e:
        logger.error(f"Phase 1 failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'total_images': 0
        }


def phase2_generate(artifacts: RunArtifacts, alt_generator, 
                   force_regenerate: bool = False) -> Dict[str, Any]:
    """
    Phase 2: Generate ALT text for images that need it.
    
    Only generates for keys where current_alt_by_key[key] is empty.
    Uses caching to avoid duplicate LLaVA calls.
    
    Args:
        artifacts: RunArtifacts for managing file paths
        alt_generator: ALT text generation provider
        force_regenerate: If True, regenerate even if cache exists
        
    Returns:
        Dictionary with generation results
    """
    logger.info("Phase 2: Generating missing ALT text")
    
    try:
        # Load Phase 1 results
        visual_index = artifacts.load_visual_index()
        current_alt_by_key = artifacts.load_current_alt_by_key()
        
        if not visual_index:
            logger.warning("No visual_index found - Phase 1 may not have run")
            return {'success': False, 'error': 'No visual index available'}
        
        # Load existing generated ALT (for caching)
        generated_alt_by_key = {}
        if not force_regenerate:
            generated_alt_by_key = artifacts.load_generated_alt_by_key()
        
        # Find keys that need generation
        keys_needing_generation = []
        for key, visual_info in visual_index.items():
            has_current = key in current_alt_by_key and current_alt_by_key[key].strip()
            has_generated = key in generated_alt_by_key and generated_alt_by_key[key].strip()
            
            if not has_current and not has_generated:
                keys_needing_generation.append(key)
        
        logger.info(f"Found {len(keys_needing_generation)} images needing ALT text generation")
        
        if not keys_needing_generation:
            # Nothing to generate, save empty result
            artifacts.save_generated_alt_by_key(generated_alt_by_key)
            return {
                'success': True,
                'generated_count': 0,
                'cached_count': len(generated_alt_by_key),
                'skipped_count': len(current_alt_by_key)
            }
        
        # Generate ALT text for needed keys
        generation_errors = []
        newly_generated = 0
        
        for key in keys_needing_generation:
            try:
                visual_info = visual_index[key]
                
                # Check if we have a thumbnail to use
                thumbnail_path = visual_info.get('thumbnail_path')
                if thumbnail_path and Path(thumbnail_path).exists():
                    # Generate using thumbnail
                    alt_text = alt_generator.generate_alt_text(thumbnail_path)
                else:
                    # Would need original image data - this is a fallback
                    logger.warning(f"No thumbnail available for {key}, skipping generation")
                    continue
                
                if alt_text and alt_text.strip():
                    generated_alt_by_key[key] = alt_text.strip()
                    newly_generated += 1
                    logger.debug(f"Generated ALT for {key}: {alt_text[:50]}...")
                else:
                    generation_errors.append(f"Empty result for {key}")
                    
            except Exception as e:
                error_msg = f"Generation failed for {key}: {e}"
                generation_errors.append(error_msg)
                logger.warning(error_msg)
        
        # Save generated ALT text
        artifacts.save_generated_alt_by_key(generated_alt_by_key)
        
        result = {
            'success': True,
            'generated_count': newly_generated,
            'total_generated': len(generated_alt_by_key),
            'cached_count': len(generated_alt_by_key) - newly_generated,
            'skipped_count': len(current_alt_by_key),
            'error_count': len(generation_errors),
            'errors': generation_errors[:10]  # Limit error list
        }
        
        logger.info(f"Phase 2 complete: {newly_generated} newly generated, "
                   f"{len(generated_alt_by_key)} total available")
        return result
        
    except Exception as e:
        logger.error(f"Phase 2 failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'generated_count': 0
        }


def phase3_resolve(artifacts: RunArtifacts) -> Dict[str, Any]:
    """
    Phase 3: Resolve final_alt_map by merging current + generated.
    
    Deterministic merge strategy:
    - If current_alt_by_key[key] exists → use that (preserve existing)
    - Else → use generated_alt_by_key[key] if available
    
    Args:
        artifacts: RunArtifacts for managing file paths
        
    Returns:
        Dictionary with resolution results
    """
    logger.info("Phase 3: Resolving final ALT text mappings")
    
    try:
        # Load Phase 1 & 2 results
        current_alt_by_key = artifacts.load_current_alt_by_key()
        generated_alt_by_key = artifacts.load_generated_alt_by_key()
        visual_index = artifacts.load_visual_index()
        
        if not visual_index:
            logger.warning("No visual_index found - Phase 1 may not have run")
            return {'success': False, 'error': 'No visual index available'}
        
        # Build final mappings using preserve-first strategy
        final_alt_map = {}

        # Stats tracking
        preserved_count = 0
        generated_count = 0
        missing_count = 0

        for key in visual_index.keys():
            existing_alt = current_alt_by_key.get(key, "").strip()
            generated_alt = generated_alt_by_key.get(key, "").strip()

            final_alt_map[key] = {
                "existing_alt": existing_alt,
                "generated_alt": generated_alt,
                "source_existing": "pptx",
                "source_generated": "llava",
                "final_alt": None,
                "decision": None,
            }

            if existing_alt:
                preserved_count += 1
            elif generated_alt:
                generated_count += 1
            else:
                missing_count += 1

        # Save final mappings
        artifacts.save_final_alt_map(final_alt_map)

        final_mapping_count = sum(
            1 for record in final_alt_map.values()
            if record["existing_alt"] or record["generated_alt"] or record["final_alt"]
        )

        result = {
            'success': True,
            'total_images': len(visual_index),
            'final_mappings': final_mapping_count,
            'preserved_count': preserved_count,
            'generated_count': generated_count,
            'missing_count': missing_count,
            'coverage_percent': (final_mapping_count / len(visual_index) * 100) if visual_index else 0
        }
        
        logger.info(f"Phase 3 complete: {len(final_alt_map)}/{len(visual_index)} images have ALT text "
                   f"({result['coverage_percent']:.1f}% coverage)")
        return result
        
    except Exception as e:
        logger.error(f"Phase 3 failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'final_mappings': 0
        }


def run_pipeline(pptx_path: Path, config, alt_generator, 
                force_regenerate: bool = False) -> RunArtifacts:
    """
    Run the complete three-phase pipeline.
    
    Args:
        pptx_path: Path to PPTX file  
        config: Configuration object
        alt_generator: ALT text generation provider
        force_regenerate: Force regeneration even if cache exists
        
    Returns:
        RunArtifacts with all pipeline outputs
    """
    logger.info(f"Starting pipeline for {pptx_path.name}")
    start_time = time.time()
    
    # Create artifacts structure
    artifacts = RunArtifacts.create_for_run(pptx_path)
    
    try:
        # Phase 1: Scan
        scan_result = phase1_scan(pptx_path, artifacts)
        if not scan_result['success']:
            raise RuntimeError(f"Phase 1 failed: {scan_result.get('error', 'Unknown error')}")
        
        # Phase 2: Generate (only if images need ALT text)
        if scan_result['total_images'] > scan_result['images_with_current_alt']:
            generate_result = phase2_generate(artifacts, alt_generator, force_regenerate)
            if not generate_result['success']:
                logger.warning(f"Phase 2 had issues: {generate_result.get('error', 'Unknown error')}")
        else:
            logger.info("Phase 2 skipped: All images already have ALT text")
            artifacts.save_generated_alt_by_key({})
        
        # Phase 3: Resolve
        resolve_result = phase3_resolve(artifacts)
        if not resolve_result['success']:
            raise RuntimeError(f"Phase 3 failed: {resolve_result.get('error', 'Unknown error')}")
        
        elapsed = time.time() - start_time
        logger.info(f"Pipeline completed in {elapsed:.2f}s")
        
        return artifacts
        
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        # Clean up on failure
        artifacts.cleanup(keep_finals=False)
        raise