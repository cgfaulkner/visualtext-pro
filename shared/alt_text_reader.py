"""
ALT Text Reader Utility - Single source of truth for reading existing ALT text
Handles all shape types: pictures, autoshapes, placeholders, connectors, groups, graphic frames
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Namespace definitions for XPath queries
PPTX_NSMAP = {
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'pic': 'http://schemas.openxmlformats.org/drawingml/2006/picture',
    'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart',
}

def _safe_xpath(element, xpath_expr, namespaces=None):
    """Execute an XPath on python-pptx BaseOxmlElement or plain lxml element."""
    el = getattr(element, "_element", element)
    try:
        return el.xpath(xpath_expr)  # python-pptx injects namespaces
    except Exception:
        ns = namespaces or getattr(el, "nsmap", None) or PPTX_NSMAP
        return el.xpath(xpath_expr, namespaces=ns)


def read_existing_alt(shape) -> str:
    """
    Returns normalized string from cNvPr @descr or @title across all shape types:
    - pictures (p:nvPicPr/p:cNvPr)
    - autoshapes/placeholders (p:nvSpPr/p:cNvPr)
    - graphic frames (p:nvGraphicFramePr/p:cNvPr)
    - connectors (p:nvCxnSpPr/p:cNvPr)
    - groups (p:nvGrpSpPr/p:cNvPr)  -> also check children for inherited ALT
    
    Prefers @descr, falls back to @title, returns empty string if none.
    """
    try:
        element = getattr(shape, "_element", None) or getattr(shape, "element", None)
        if element is None:
            return ""

        # Define XPath patterns for all shape types, ordered by specificity
        xpath_patterns = [
            ".//p:nvPicPr/p:cNvPr",           # Pictures
            ".//p:nvSpPr/p:cNvPr",            # Autoshapes/placeholders
            ".//p:nvGraphicFramePr/p:cNvPr",  # Graphic frames (charts, tables)
            ".//p:nvCxnSpPr/p:cNvPr",         # Connectors
            ".//p:nvGrpSpPr/p:cNvPr",         # Groups
            ".//p:cNvPr"                      # Generic fallback
        ]

        # Try each pattern to find cNvPr elements
        for xpath in xpath_patterns:
            try:
                nodes = _safe_xpath(element, xpath, PPTX_NSMAP)
                if nodes:
                    cNvPr = nodes[0]
                    
                    # Prefer @descr (ALT text), fall back to @title
                    alt_text = cNvPr.get("descr", "").strip()
                    if alt_text:
                        return alt_text
                    
                    title_text = cNvPr.get("title", "").strip()
                    if title_text:
                        return title_text
                        
            except Exception as e:
                logger.debug(f"XPath pattern {xpath} failed: {e}")
                continue

        # Special handling for groups - check if any children have ALT text
        if _is_group_shape(element):
            return _read_group_children_alt(element)

        return ""
        
    except Exception as e:
        logger.debug(f"Error reading ALT text from shape: {e}")
        return ""


def _is_group_shape(element) -> bool:
    """Check if the element is a group shape."""
    try:
        group_nodes = _safe_xpath(element, ".//p:grpSp", PPTX_NSMAP)
        return len(group_nodes) > 0
    except Exception:
        return False


def _read_group_children_alt(group_element) -> str:
    """
    For group shapes, check if any child shapes have ALT text.
    Returns the first non-empty ALT text found, or empty string.
    """
    try:
        # Find all child shapes in the group
        child_shapes = _safe_xpath(group_element, ".//p:grpSp//p:sp | .//p:grpSp//p:pic", PPTX_NSMAP)
        
        for child in child_shapes:
            # Check each child for ALT text using the same pattern
            for xpath in [".//p:nvPicPr/p:cNvPr", ".//p:nvSpPr/p:cNvPr", ".//p:cNvPr"]:
                try:
                    nodes = _safe_xpath(child, xpath, PPTX_NSMAP)
                    if nodes:
                        cNvPr = nodes[0]
                        alt_text = cNvPr.get("descr", "").strip()
                        if alt_text:
                            return alt_text
                        title_text = cNvPr.get("title", "").strip()
                        if title_text:
                            return title_text
                except Exception:
                    continue
        
        return ""
        
    except Exception as e:
        logger.debug(f"Error reading group children ALT text: {e}")
        return ""


def has_existing_alt(shape) -> bool:
    """
    Check if shape has any existing ALT text (non-empty).
    """
    alt_text = read_existing_alt(shape)
    return bool(alt_text.strip())


def get_alt_text_source(shape) -> str:
    """
    Returns information about where the ALT text was found:
    'descr', 'title', 'group_child', or 'none'
    """
    try:
        element = getattr(shape, "_element", None) or getattr(shape, "element", None)
        if element is None:
            return "none"

        xpath_patterns = [
            ".//p:nvPicPr/p:cNvPr",
            ".//p:nvSpPr/p:cNvPr", 
            ".//p:nvGraphicFramePr/p:cNvPr",
            ".//p:nvCxnSpPr/p:cNvPr",
            ".//p:nvGrpSpPr/p:cNvPr",
            ".//p:cNvPr"
        ]

        for xpath in xpath_patterns:
            try:
                nodes = _safe_xpath(element, xpath, PPTX_NSMAP)
                if nodes:
                    cNvPr = nodes[0]
                    if cNvPr.get("descr", "").strip():
                        return "descr"
                    if cNvPr.get("title", "").strip():
                        return "title"
            except Exception:
                continue

        # Check for group children
        if _is_group_shape(element):
            group_alt = _read_group_children_alt(element)
            if group_alt:
                return "group_child"

        return "none"
        
    except Exception:
        return "none"