#!/usr/bin/env python3
"""
Manifest-Based PPTX ALT Text Injector
=====================================

Injects ALT text into PPTX files reading only from the manifest.
No LLaVA calls - all ALT text comes from the manifest SSOT.
"""

from __future__ import annotations
import logging
from pathlib import Path
from typing import Dict, Any, Literal

from alt_manifest import AltManifest

logger = logging.getLogger(__name__)


def inject_from_manifest(
    pptx_path: str,
    manifest_path: str,
    output_path: str = None,
    mode: Literal["preserve", "replace"] = "preserve",
    run_id: str | None = None,
) -> Dict[str, Any]:
    """
    Inject ALT text from manifest into PPTX file.
    
    Args:
        pptx_path: Path to input PPTX file
        manifest_path: Path to manifest JSONL file  
        output_path: Path for output PPTX (default: overwrite input)
        mode: "preserve" (keep existing) or "replace" (overwrite existing)
        run_id: Optional identifier for tracking pipeline runs
        
    Returns:
        Injection results with statistics and decision logging
    """
    logger.info("RUN_ID=%s manifest=%s", run_id, manifest_path)
    logger.info("Injecting ALT text from manifest into %s (mode: %s)", pptx_path, mode)
    
    if output_path is None:
        output_path = pptx_path
    
    try:
        # Load manifest
        manifest = AltManifest(Path(manifest_path))
        entries = manifest.get_all_entries()
        
        if not entries:
            logger.warning("No entries found in manifest")
            return {
                'success': True,
                'total_entries': 0,
                'injected_successfully': 0,
                'skipped_existing': 0,
                'errors': []
            }
        
        logger.info(f"Found {len(entries)} entries in manifest")
        
        # Perform injection using existing robust injector
        result = _inject_using_robust_injector(pptx_path, entries, output_path, mode, manifest)
        
        return result
        
    except Exception as e:
        logger.error(f"Manifest-based injection failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'total_entries': 0,
            'injected_successfully': 0
        }


def _inject_using_robust_injector(pptx_path: str, entries, output_path: str, 
                                 mode: str, manifest: AltManifest) -> Dict[str, Any]:
    """Use the existing robust injector with manifest data."""
    try:
        # Convert manifest entries to the mapping format expected by injector
        # Use final_alt as primary source, with suggested_alt as fallback
        alt_text_mapping = {}
        decision_log = {}
        
        for entry in entries:
            # Determine final ALT text to inject
            alt_to_inject = ""
            decision_reason = ""
            
            if mode == "preserve" and entry.had_existing_alt and entry.existing_alt.strip():
                # Preserve mode with existing ALT - use existing
                alt_to_inject = entry.existing_alt.strip()
                decision_reason = "preserved_existing"
            elif entry.final_alt.strip():
                # Use final_alt (our normalized, processed text)
                alt_to_inject = entry.final_alt.strip()
                decision_reason = f"used_final_alt_from_{entry.decision_reason or entry.source}"
            elif entry.suggested_alt.strip():
                # Fallback to legacy suggested_alt field
                alt_to_inject = entry.suggested_alt.strip()
                decision_reason = f"fallback_to_suggested_alt_from_{entry.source}"
            elif mode == "replace" and entry.existing_alt.strip():
                # Replace mode but no new ALT generated - keep existing
                alt_to_inject = entry.existing_alt.strip()
                decision_reason = "replace_mode_but_no_new_alt"
            else:
                # No ALT text available - skip this entry
                logger.debug(f"No ALT text available for {entry.key}, skipping")
                continue
            
            if alt_to_inject:
                alt_text_mapping[entry.key] = alt_to_inject
                decision_log[entry.key] = {
                    'alt_used': alt_to_inject,
                    'decision_reason': decision_reason,
                    'shape_type': entry.shape_type,
                    'is_group_child': entry.is_group_child,
                    'had_existing_alt': entry.had_existing_alt,
                    'llava_called': entry.llava_called
                }
        
        logger.info(f"Prepared {len(alt_text_mapping)} ALT text mappings for injection")
        
        # Use existing robust injector
        from core.pptx_alt_injector import PPTXAltTextInjector  
        from shared.config_manager import ConfigManager
        
        config_manager = ConfigManager()
        injector = PPTXAltTextInjector(config_manager)
        
        # Perform injection with decision logging
        result = injector.inject_alt_text_from_mapping(
            pptx_path,
            alt_text_mapping,
            output_path,
            mode=mode
        )
        
        # Add decision logging for traceability
        if result['success']:
            stats = result.get('statistics', {})
            
            # Log detailed decisions for each entry
            for key, decision_info in decision_log.items():
                manifest.log_decision(
                    key, 
                    mode, 
                    decision_info['alt_used'], 
                    f"{decision_info['decision_reason']} | shape: {decision_info['shape_type']} | "
                    f"group_child: {decision_info['is_group_child']} | "
                    f"had_existing: {decision_info['had_existing_alt']} | "
                    f"llava_called: {decision_info['llava_called']}"
                )
            
            # Log summary statistics
            shape_types = {}
            for decision_info in decision_log.values():
                shape_type = decision_info['shape_type']
                shape_types[shape_type] = shape_types.get(shape_type, 0) + 1
            
            logger.info(f"Injection completed: {stats.get('injected_successfully', 0)} elements updated")
            logger.info(f"Shape type distribution: {shape_types}")
            logger.info(f"Decision reasons: {[d['decision_reason'] for d in decision_log.values()]}")
            
        return result
        
    except Exception as e:
        logger.error(f"Robust injector failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'total_entries': len(entries),
            'injected_successfully': 0
        }


def validate_manifest_for_injection(manifest_path: str) -> Dict[str, Any]:
    """
    Validate that manifest has the data needed for injection.
    
    Returns:
        Validation results with statistics
    """
    try:
        manifest = AltManifest(Path(manifest_path))
        entries = manifest.get_all_entries()
        
        if not entries:
            return {
                'valid': False,
                'error': 'No entries found in manifest',
                'total_entries': 0
            }
        
        injectable_count = 0
        missing_alt_text = 0
        by_shape_type = {}
        by_decision_reason = {}
        
        for entry in entries:
            # Count by shape type
            shape_type = entry.shape_type
            by_shape_type[shape_type] = by_shape_type.get(shape_type, 0) + 1
            
            # Count by decision reason
            decision_reason = entry.decision_reason or entry.source
            by_decision_reason[decision_reason] = by_decision_reason.get(decision_reason, 0) + 1
            
            # Check if entry has injectable ALT text
            has_alt = (entry.final_alt and entry.final_alt.strip()) or \
                     (entry.suggested_alt and entry.suggested_alt.strip()) or \
                     (entry.existing_alt and entry.existing_alt.strip())
                     
            if has_alt:
                injectable_count += 1
            else:
                missing_alt_text += 1
        
        stats = manifest.get_statistics()
        
        return {
            'valid': True,
            'total_entries': len(entries),
            'injectable_entries': injectable_count,
            'missing_alt_text': missing_alt_text,
            'by_shape_type': by_shape_type,
            'by_decision_reason': by_decision_reason,
            'llava_calls_in_manifest': stats['llava_calls_made'],
            'manifest_statistics': stats
        }
        
    except Exception as e:
        return {
            'valid': False,
            'error': str(e),
            'total_entries': 0
        }