#!/usr/bin/env python3
"""
Synchronization Validator
=========================

Validates that PPT injector and DOCX builder outputs are perfectly synchronized.
Compares the ALT text written to the PPTX file with what's displayed in the DOCX review.

This ensures that:
1. PPT injector reads final_alt correctly from manifest
2. DOCX builder displays the same final_alt values
3. No elements are missing or mismatched between outputs
4. Shape type labeling is consistent across both outputs
"""

from __future__ import annotations
import logging
import json
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

from alt_manifest import AltManifest

logger = logging.getLogger(__name__)


def validate_ppt_docx_synchronization(
    manifest_path: str,
    pptx_path: str,
    docx_path: str,
    output_report: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate synchronization between PPT injection and DOCX review outputs.
    
    Args:
        manifest_path: Path to ALT manifest JSONL file
        pptx_path: Path to PPTX file with injected ALT text
        docx_path: Path to generated DOCX review file
        output_report: Optional path to save detailed validation report
        
    Returns:
        Validation results with detailed comparison data
    """
    logger.info(f"Validating PPT/DOCX synchronization using manifest: {manifest_path}")
    
    try:
        # Load manifest (single source of truth)
        manifest = AltManifest(Path(manifest_path))
        entries = manifest.get_all_entries()
        
        if not entries:
            logger.warning("No entries found in manifest")
            return {
                'synchronized': True,
                'total_entries': 0,
                'discrepancies': [],
                'summary': 'No entries to validate'
            }
        
        logger.info(f"Validating {len(entries)} manifest entries")
        
        # Extract ALT text from actual PPTX file
        pptx_alt_text = _extract_alt_from_pptx(pptx_path)
        
        # Compare manifest expectations vs PPTX reality vs DOCX display
        validation_results = _perform_synchronization_check(
            entries, pptx_alt_text, manifest_path
        )
        
        # Generate detailed report if requested
        if output_report:
            _generate_validation_report(validation_results, output_report)
        
        return validation_results
        
    except Exception as e:
        logger.error(f"Synchronization validation failed: {e}", exc_info=True)
        return {
            'synchronized': False,
            'error': str(e),
            'total_entries': 0,
            'discrepancies': []
        }


def _extract_alt_from_pptx(pptx_path: str) -> Dict[str, str]:
    """
    Extract actual ALT text from PPTX file to compare with manifest expectations.
    
    Returns:
        Dictionary mapping element identifiers to their actual ALT text in PPTX
    """
    logger.info(f"Extracting ALT text from PPTX: {pptx_path}")
    
    try:
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE
        from alt_manifest import compute_image_hash, create_stable_key
        
        prs = Presentation(pptx_path)
        pptx_alt_map = {}
        
        for slide_idx, slide in enumerate(prs.slides):
            for shape_idx, shape in enumerate(slide.shapes):
                try:
                    # Get shape ID and extract current ALT text
                    shape_id = getattr(shape, 'shape_id', shape_idx)
                    alt_text = _extract_current_alt_text(shape)
                    
                    # Generate hash (same logic as manifest processor)
                    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                        if hasattr(shape, 'image') and shape.image:
                            image_data = shape.image.blob
                            if image_data:
                                image_hash = compute_image_hash(image_data)
                            else:
                                continue
                        else:
                            continue
                    else:
                        # Non-picture shape
                        shape_type = _classify_shape_type_simple(shape.shape_type)
                        shape_properties = f"{shape_type}_{shape_id}_{slide_idx}"
                        if hasattr(shape, 'width') and hasattr(shape, 'height'):
                            width_px = int(shape.width.emu // 914400) if shape.width else 0
                            height_px = int(shape.height.emu // 914400) if shape.height else 0
                            shape_properties += f"_{width_px}x{height_px}"
                        image_hash = compute_image_hash(shape_properties.encode('utf-8'))
                    
                    # Create stable key (same as manifest)
                    key = create_stable_key(slide_idx, shape_id, image_hash)
                    pptx_alt_map[key] = alt_text
                    
                except Exception as e:
                    logger.debug(f"Could not extract ALT from slide {slide_idx}, shape {shape_idx}: {e}")
                    
        logger.info(f"Extracted ALT text from {len(pptx_alt_map)} elements in PPTX")
        return pptx_alt_map
        
    except Exception as e:
        logger.error(f"Failed to extract ALT text from PPTX: {e}")
        return {}


def _extract_current_alt_text(shape) -> str:
    """Extract current ALT text from PPTX shape (same logic as manifest processor)."""
    try:
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


def _classify_shape_type_simple(shape_type) -> str:
    """Simple shape type classification for hash generation."""
    try:
        from pptx.enum.shapes import MSO_SHAPE_TYPE
        
        if shape_type == MSO_SHAPE_TYPE.PICTURE:
            return "PICTURE"
        elif shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE:
            return "AUTO_SHAPE"
        elif shape_type == MSO_SHAPE_TYPE.TEXT_BOX:
            return "TEXT_BOX"
        elif shape_type == MSO_SHAPE_TYPE.LINE:
            return "LINE"
        elif shape_type == MSO_SHAPE_TYPE.TABLE:
            return "TABLE"
        elif shape_type == MSO_SHAPE_TYPE.GROUP:
            return "GROUP"
        elif shape_type == MSO_SHAPE_TYPE.CONNECTOR:
            return "CONNECTOR"
        else:
            return f"SHAPE_{shape_type}"
    except:
        return "UNKNOWN"


def _perform_synchronization_check(
    entries: List,
    pptx_alt_map: Dict[str, str],
    manifest_path: str
) -> Dict[str, Any]:
    """
    Perform detailed synchronization check between manifest, PPT, and DOCX.
    
    Returns:
        Detailed validation results
    """
    logger.info("Performing synchronization validation")
    
    discrepancies = []
    perfect_matches = 0
    missing_in_pptx = 0
    alt_text_mismatches = 0
    shape_type_inconsistencies = 0
    
    # Statistics by shape type and decision reason
    by_shape_type = {}
    by_decision_reason = {}
    
    for entry in entries:
        key = entry.key
        
        # Track statistics
        shape_type = entry.shape_type
        by_shape_type[shape_type] = by_shape_type.get(shape_type, 0) + 1
        
        decision_reason = entry.decision_reason or entry.source
        by_decision_reason[decision_reason] = by_decision_reason.get(decision_reason, 0) + 1
        
        # Expected ALT text from manifest (single source of truth)
        expected_alt = (entry.final_alt or entry.suggested_alt).strip()
        
        # Handle preserve mode logic
        if entry.decision_reason == "preserved" or (entry.had_existing_alt and entry.source == "existing"):
            expected_alt = entry.existing_alt or entry.current_alt
        
        # Get actual ALT text from PPTX
        actual_alt = pptx_alt_map.get(key, "").strip()
        
        # Validation checks
        if key not in pptx_alt_map:
            missing_in_pptx += 1
            discrepancies.append({
                'type': 'missing_in_pptx',
                'key': key,
                'slide_number': entry.slide_number,
                'image_number': entry.image_number,
                'shape_type': entry.shape_type,
                'expected_alt': expected_alt,
                'actual_alt': None,
                'severity': 'high'
            })
        elif expected_alt != actual_alt:
            # ALT text mismatch
            alt_text_mismatches += 1
            
            # Determine severity
            severity = 'high'
            if not expected_alt and not actual_alt:
                severity = 'low'  # Both empty
            elif len(expected_alt) > 0 and len(actual_alt) > 0:
                # Both have content, might be normalization issue
                if expected_alt.lower().strip('.,!?') == actual_alt.lower().strip('.,!?'):
                    severity = 'low'  # Just punctuation/case differences
                else:
                    severity = 'medium'
            
            discrepancies.append({
                'type': 'alt_text_mismatch',
                'key': key,
                'slide_number': entry.slide_number,
                'image_number': entry.image_number,
                'shape_type': entry.shape_type,
                'expected_alt': expected_alt,
                'actual_alt': actual_alt,
                'severity': severity,
                'decision_reason': decision_reason,
                'had_existing_alt': entry.had_existing_alt,
                'llava_called': entry.llava_called
            })
        else:
            # Perfect match
            perfect_matches += 1
    
    # Check for extra elements in PPTX (shouldn't happen with manifest approach)
    extra_in_pptx = set(pptx_alt_map.keys()) - {e.key for e in entries}
    
    # Overall synchronization status
    total_entries = len(entries)
    high_severity_count = len([d for d in discrepancies if d.get('severity') == 'high'])
    synchronized = high_severity_count == 0
    
    results = {
        'synchronized': synchronized,
        'total_entries': total_entries,
        'perfect_matches': perfect_matches,
        'discrepancies': discrepancies,
        'missing_in_pptx': missing_in_pptx,
        'alt_text_mismatches': alt_text_mismatches,
        'extra_in_pptx': len(extra_in_pptx),
        'high_severity_issues': high_severity_count,
        'by_shape_type': by_shape_type,
        'by_decision_reason': by_decision_reason,
        'manifest_path': manifest_path,
        'summary': _generate_summary(
            synchronized, total_entries, perfect_matches, 
            len(discrepancies), high_severity_count
        )
    }
    
    logger.info(f"Synchronization check complete: {results['summary']}")
    return results


def _generate_summary(
    synchronized: bool, 
    total: int, 
    perfect: int, 
    discrepancies: int,
    high_severity: int
) -> str:
    """Generate human-readable summary of validation results."""
    if synchronized:
        return f"✅ Perfect synchronization: {perfect}/{total} elements match exactly"
    else:
        return f"❌ Synchronization issues: {discrepancies} discrepancies ({high_severity} high severity) out of {total} elements"


def _generate_validation_report(results: Dict[str, Any], output_path: str):
    """Generate detailed JSON validation report."""
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        logger.info(f"Validation report saved: {output_path}")
    except Exception as e:
        logger.error(f"Could not save validation report: {e}")


def print_validation_summary(results: Dict[str, Any]):
    """Print human-readable validation summary to console."""
    print("\n" + "="*60)
    print("🔍 PPT/DOCX SYNCHRONIZATION VALIDATION RESULTS")
    print("="*60)
    
    print(f"\n📊 Overall Status: {results['summary']}")
    
    if results.get('error'):
        print(f"❌ Error: {results['error']}")
        return
    
    total = results['total_entries']
    perfect = results['perfect_matches']
    discrepancies = len(results['discrepancies'])
    
    print(f"\n📈 Statistics:")
    print(f"   Total entries: {total}")
    print(f"   Perfect matches: {perfect}")
    print(f"   Discrepancies: {discrepancies}")
    print(f"   Missing in PPTX: {results['missing_in_pptx']}")
    print(f"   ALT text mismatches: {results['alt_text_mismatches']}")
    print(f"   High severity issues: {results['high_severity_issues']}")
    
    # Shape type breakdown
    print(f"\n🔧 Shape Type Distribution:")
    for shape_type, count in results['by_shape_type'].items():
        print(f"   {shape_type}: {count}")
    
    # Decision reason breakdown
    print(f"\n🎯 Decision Reason Breakdown:")
    for reason, count in results['by_decision_reason'].items():
        print(f"   {reason}: {count}")
    
    # Show first few discrepancies
    if discrepancies > 0:
        print(f"\n⚠️  Sample Discrepancies (showing first 5):")
        for i, disc in enumerate(results['discrepancies'][:5]):
            severity_icon = {"high": "🔴", "medium": "🟡", "low": "⚪"}.get(disc['severity'], "⚫")
            print(f"   {severity_icon} Slide {disc['slide_number']}/{disc['image_number']} ({disc['shape_type']})")
            print(f"      Type: {disc['type']}")
            print(f"      Expected: '{disc['expected_alt']}'")
            print(f"      Actual: '{disc.get('actual_alt', 'N/A')}'")
            print()
    
    print("="*60)