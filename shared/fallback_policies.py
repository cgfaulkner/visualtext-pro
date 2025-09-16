"""
Fallback Policy Implementation - A/B/C fallback handling with quality gate
Handles fallback strategies when ALT text generation fails
"""

import logging
import re
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)


# --- XML tag helper functions for robust shape type detection ---
def _element_of(shape):
    """Extract the underlying XML element from a shape object."""
    return getattr(shape, "_element", None) or getattr(shape, "element", None)


def is_connector(shape):
    """Check if shape is a connector using XML tag inspection."""
    el = _element_of(shape)
    return bool(el is not None and el.tag.endswith('}cxnSp'))  # p:cxnSp


# Quality gate criteria
QUALITY_GATE_BLOCKED_WORDS = {
    'unknown', 'image', 'picture', 'graphic', 'icon', 'shape'
}

def passes_quality_gate(text: str) -> bool:
    """
    Quality gate for fallback text - rejects low-value fallbacks.
    
    Criteria:
    - Reject if text contains blocked words (unknown, image, picture, graphic, icon, shape)
    - Require terminal punctuation when length > 6 words
    - Require at least one non-geometric noun (basic keyword list)
    - Max length 140 chars
    
    Args:
        text: Text to evaluate
        
    Returns:
        bool: True if text passes quality gate
    """
    if not text or not text.strip():
        return False
    
    text = text.strip().lower()
    
    # Max length check
    if len(text) > 140:
        return False
    
    # Check for blocked words
    for blocked_word in QUALITY_GATE_BLOCKED_WORDS:
        if blocked_word in text:
            return False
    
    # Word count for punctuation requirement
    words = text.split()
    if len(words) > 6:
        # Require terminal punctuation for longer text
        if not text.endswith(('.', '!', '?')):
            return False
    
    # Basic non-geometric noun check (simplified)
    # This is a basic implementation - could be enhanced with NLP
    meaningful_words = {
        'blue', 'red', 'green', 'yellow', 'orange', 'purple', 'black', 'white',
        'square', 'circle', 'triangle', 'rectangle', 'line', 'box', 'text',
        'button', 'chart', 'graph', 'table', 'diagram', 'map', 'photo'
    }
    
    has_meaningful_word = any(word in meaningful_words for word in words)
    if len(words) >= 3 and not has_meaningful_word:
        return False
    
    return True


def passes_lenient_quality_gate(text: str) -> bool:
    """
    Lenient quality gate for generated text - allows more patterns that are legitimate.

    Args:
        text: Text to evaluate

    Returns:
        bool: True if text passes lenient quality gate
    """
    if not text or not text.strip():
        return False

    text_stripped = text.strip()

    # Max length check
    if len(text_stripped) > 200:
        return False

    # Block only obviously templated/broken content
    blocked_patterns = [
        "unknown (",
        "text placeholder (",
        "shape with no specific content",
        "[Generated description not available]",
        "error:",
        "failed to",
        "could not"
    ]

    text_lower = text_stripped.lower()
    for pattern in blocked_patterns:
        if pattern in text_lower:
            return False

    # Allow anything else for generated content
    return True


def humanish_stub(shape) -> str:
    """
    Create a minimal, humanish fallback description for a shape.
    Summarizes visible geometry only when meaningful.
    
    Args:
        shape: PowerPoint shape object
        
    Returns:
        str: Minimal descriptive text
    """
    try:
        # Try to extract basic shape information
        shape_type = "shape"
        dimensions = ""
        
        # Get shape dimensions if available
        try:
            if hasattr(shape, 'width') and hasattr(shape, 'height'):
                width_px = int(shape.width.pt)
                height_px = int(shape.height.pt)
                dimensions = f"({width_px}×{height_px}px)"
                
                # Determine orientation for lines/connectors
                if hasattr(shape, 'shape_type'):
                    shape_type_val = getattr(shape.shape_type, 'value', None)
                    if shape_type_val in [5, 6]:  # Line or connector types
                        if width_px > height_px * 3:
                            shape_type = "horizontal line"
                        elif height_px > width_px * 3:
                            shape_type = "vertical line"
                        else:
                            shape_type = "diagonal line"
                    elif shape_type_val == 1:  # Rectangle
                        shape_type = "rectangle"
                    elif shape_type_val == 2:  # Oval
                        shape_type = "oval"
                    else:
                        shape_type = "shape"
                        
        except Exception:
            pass
        
        # Try to get color information if available
        color_info = ""
        try:
            if hasattr(shape, 'fill') and hasattr(shape.fill, 'fore_color'):
                # This is simplified - could be enhanced
                color_info = ""  # Omit color for now to keep it simple
        except Exception:
            pass
        
        # Create minimal description
        if dimensions and color_info:
            return f"{color_info} {shape_type} {dimensions}".strip()
        elif dimensions:
            return f"{shape_type} {dimensions}".strip()
        else:
            return f"{shape_type}".strip()
            
    except Exception as e:
        logger.debug(f"Error creating shape fallback: {e}")
        return "shape element"


def is_decorative(shape) -> bool:
    """
    Simple decorative detection for fallback policy.
    This is a basic implementation - should integrate with existing decorative detection.
    
    Args:
        shape: PowerPoint shape object
        
    Returns:
        bool: True if shape appears decorative
    """
    try:
        # Check shape name for decorative indicators
        if hasattr(shape, 'name'):
            name = str(shape.name).lower()
            decorative_indicators = ['logo', 'border', 'line', 'divider', 'decoration']
            if any(indicator in name for indicator in decorative_indicators):
                return True
        
        # Check dimensions - very small shapes might be decorative
        if hasattr(shape, 'width') and hasattr(shape, 'height'):
            try:
                width_px = int(shape.width.pt)
                height_px = int(shape.height.pt)
                area = width_px * height_px
                
                # Very small areas are likely decorative
                if area < 100:  # Less than 10x10 pixels
                    return True
            except Exception:
                pass
        
        return False
        
    except Exception:
        return False


def apply_fallback_policy(
    generation_result: Dict[str, Any],
    existing_alt: str,
    shape,
    fallback_policy: str,
    element_key: str
) -> Tuple[Optional[str], str, Dict[str, Any]]:
    """
    Apply the specified fallback policy when generation fails.
    
    Args:
        generation_result: Result from ALT text generation ({"status": "ok/fail", ...})
        existing_alt: Existing ALT text from shape
        shape: PowerPoint shape object
        fallback_policy: Policy to apply ("none", "doc-only", "ppt-gated")
        element_key: Element identifier for logging
        
    Returns:
        Tuple of (alt_text_for_ppt, suggested_alt_for_review, review_status_info)
        - alt_text_for_ppt: Text to write to PPT (None = don't write)
        - suggested_alt_for_review: Text for review document
        - review_status_info: Dict with status info for review doc
    """
    if generation_result.get("status") == "ok":
        # Generation succeeded - return the generated text
        generated_text = generation_result.get("text", "")
        return generated_text, generated_text, {
            "status": "generated",
            "method": "ai_generation"
        }
    
    # Generation failed - apply fallback policy
    failure_reason = generation_result.get("reason", "unknown_error")
    
    if fallback_policy == "none":
        return None, "", {
            "status": f"NEEDS ALT",
            "reason": failure_reason,
            "method": "none_policy"
        }
    
    elif fallback_policy == "doc-only":
        fallback_text = humanish_stub(shape)
        return None, f"FALLBACK: {fallback_text}", {
            "status": f"AUTO-LOWCONF",
            "reason": failure_reason,
            "method": "doc_only_policy"
        }
    
    elif fallback_policy == "ppt-gated":
        fallback_text = humanish_stub(shape)
        
        # Check quality gate and other conditions
        if (passes_quality_gate(fallback_text) and 
            not existing_alt.strip() and 
            not is_decorative(shape)):
            
            return fallback_text, fallback_text, {
                "status": "FALLBACK_INJECTED",
                "reason": failure_reason,
                "method": "ppt_gated_policy"
            }
        else:
            # Failed quality gate or other conditions
            return None, "", {
                "status": f"NEEDS ALT",
                "reason": failure_reason,
                "method": "ppt_gated_rejected"
            }
    
    else:
        logger.warning(f"Unknown fallback policy: {fallback_policy}")
        return None, "", {
            "status": f"NEEDS ALT",
            "reason": f"unknown_policy_{fallback_policy}",
            "method": "error"
        }


def get_review_status_display(status_info: Dict[str, Any]) -> str:
    """
    Convert status info to display string for review documents.
    
    Args:
        status_info: Status information dict
        
    Returns:
        str: Display string for review document
    """
    status = status_info.get("status", "unknown")
    reason = status_info.get("reason", "")
    
    if status == "generated":
        return "Generated"
    elif status == "preserved":
        return "Preserved"
    elif status.startswith("NEEDS ALT"):
        if reason:
            return f"Needs ALT ({reason})"
        return "Needs ALT"
    elif status.startswith("AUTO-LOWCONF"):
        if reason:
            return f"Auto Low-Conf ({reason})"
        return "Auto Low-Confidence"
    elif status == "FALLBACK_INJECTED":
        return "Fallback Injected"
    else:
        return status


def apply_for_ppt_injection(
    proposed_text: str,
    element_kind: str,
    quality_flags: Dict[str, Any],
    policy: str,
    shape=None
) -> Optional[str]:
    """
    Centralized gate for any text entering PowerPoint.
    Blocks templated strings and enforces policy rules.
    
    Args:
        proposed_text: Text proposed for injection
        element_kind: Type of element (picture, shape, etc.)
        quality_flags: Dict with quality indicators
        policy: Fallback policy (none, doc-only, ppt-gated)
        
    Returns:
        Text to inject into PPT, or None to skip injection
    """
    if not proposed_text or not proposed_text.strip():
        return None
    
    text = proposed_text.strip()
    
    # Special handling for connectors - treat as decorative by default
    if shape and is_connector(shape):
        # Only allow explicit authored text for connectors
        if not quality_flags.get("is_generated", False):
            logger.debug("Blocking connector - no explicit authored text")
            return None
    
    # Group roll-up: If parent group has ALT and children are decorative, 
    # don't backfill children with fallbacks
    if shape and quality_flags.get("is_fallback", False):
        try:
            # Check if this shape is in a group that already has ALT text
            parent_element = getattr(shape, '_element', None)
            if parent_element is not None:
                # Simple check - if we're in a group context, be more conservative
                if hasattr(shape, '_parent') and quality_flags.get("is_fallback", False):
                    logger.debug("Blocking fallback for shape in group context")
                    return None
        except Exception:
            pass
    
    # Hard-block templated fallback strings
    templated_patterns = [
        "This is a PowerPoint shape",
        "unknown (",
        "text placeholder (",
        "chart (",
        "table (",
        "group shape (",
        "connector (",
        "shape with no specific content",
        "[Generated description not available]"
    ]
    
    for pattern in templated_patterns:
        if pattern in text:
            logger.debug(f"Blocking templated string from PPT injection: {pattern}")
            return None
    
    # Policy enforcement
    if policy == "none":
        # Only allow high-quality generated text
        if not quality_flags.get("is_generated", False):
            return None
        # For generated content, use more lenient quality checks
        if quality_flags.get("is_generated", False):
            # Allow generated text but still block obviously bad content
            if not passes_lenient_quality_gate(text):
                return None
        else:
            if not passes_quality_gate(text):
                return None
    
    elif policy == "doc-only":
        # No fallbacks go to PPT at all
        if quality_flags.get("is_fallback", False):
            return None
    
    elif policy == "ppt-gated":
        # Allow fallbacks but with quality gate
        if quality_flags.get("is_fallback", False):
            if not passes_quality_gate(text):
                return None
    
    return text