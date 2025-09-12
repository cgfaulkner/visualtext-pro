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


def inject_from_manifest(pptx_path: str, manifest_path: str, 
                        output_path: str = None,
                        mode: Literal["preserve", "replace"] = "preserve") -> Dict[str, Any]:
    """
    Inject ALT text from manifest into PPTX file.
    
    Args:
        pptx_path: Path to input PPTX file
        manifest_path: Path to manifest JSONL file  
        output_path: Path for output PPTX (default: overwrite input)
        mode: "preserve" (keep existing) or "replace" (overwrite existing)
        
    Returns:
        Injection results with statistics and decision logging
    """
    logger.info(f"Injecting ALT text from manifest into {pptx_path} (mode: {mode})")
    
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
        alt_text_mapping = {}
        for entry in entries:
            if entry.suggested_alt:
                alt_text_mapping[entry.key] = entry.suggested_alt
        
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
            
            # Log decisions for each entry
            for entry in entries:
                if entry.key in alt_text_mapping:
                    if mode == "preserve" and entry.current_alt.strip():
                        # In preserve mode with existing ALT, log what actually happened
                        alt_used = "current" if entry.source == "existing" else "suggested"
                        reasoning = f"preserve mode, source: {entry.source}"
                    else:
                        alt_used = "suggested" 
                        reasoning = f"source: {entry.source}, injected successfully"
                        
                    manifest.log_decision(entry.key, mode, alt_used, reasoning)
            
            logger.info(f"Injection completed: {stats.get('injected_successfully', 0)} images updated")
            
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
        missing_suggested_alt = 0
        
        for entry in entries:
            if entry.suggested_alt and entry.suggested_alt.strip():
                injectable_count += 1
            else:
                missing_suggested_alt += 1
        
        stats = manifest.get_statistics()
        
        return {
            'valid': True,
            'total_entries': len(entries),
            'injectable_entries': injectable_count,
            'missing_suggested_alt': missing_suggested_alt,
            'llava_calls_in_manifest': stats['llava_calls_made'],
            'manifest_statistics': stats
        }
        
    except Exception as e:
        return {
            'valid': False,
            'error': str(e),
            'total_entries': 0
        }