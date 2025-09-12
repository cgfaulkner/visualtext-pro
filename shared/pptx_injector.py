#!/usr/bin/env python3
"""
PPTX ALT Text Injector - Clean Pipeline Approach
===============================================

Injects ALT text into PPTX files using final_alt_map.json from Phase 3.
Supports both preserve and replace modes as configured.
"""

from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Dict, Any, Literal

logger = logging.getLogger(__name__)


def inject_from_map(pptx_path: str, final_alt_map_path: str, 
                   mode: Literal["preserve", "replace"] = "preserve") -> Dict[str, Any]:
    """
    Inject ALT text from final_alt_map.json into PPTX file.
    
    Args:
        pptx_path: Path to PPTX file to modify
        final_alt_map_path: Path to final_alt_map.json from Phase 3
        mode: "preserve" (keep existing) or "replace" (overwrite existing)
        
    Returns:
        Dictionary with injection results
    """
    logger.info(f"Injecting ALT text into {pptx_path} (mode: {mode})")
    
    try:
        # Load final ALT text mappings
        with open(final_alt_map_path, 'r', encoding='utf-8') as f:
            final_alt_map = json.load(f)
            
        if not final_alt_map:
            logger.warning("No ALT text mappings found in final_alt_map")
            return {
                'success': True,
                'injected_successfully': 0,
                'total_mappings': 0,
                'skipped_existing': 0,
                'errors': []
            }
        
        # Inject using existing robust injector
        from core.pptx_alt_injector import PPTXAltTextInjector
        from shared.config_manager import ConfigManager
        
        # Use default config for injector
        config_manager = ConfigManager()
        injector = PPTXAltTextInjector(config_manager)
        
        # Perform injection
        result = injector.inject_alt_text_from_mapping(
            pptx_path, 
            final_alt_map,
            pptx_path,  # Overwrite original
            mode=mode
        )
        
        if result['success']:
            stats = result.get('statistics', {})
            logger.info(f"Injection complete: {stats.get('injected_successfully', 0)} images updated")
        else:
            logger.error(f"Injection failed: {result.get('error', 'Unknown error')}")
            
        return result
        
    except Exception as e:
        logger.error(f"ALT text injection failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'injected_successfully': 0,
            'total_mappings': 0
        }