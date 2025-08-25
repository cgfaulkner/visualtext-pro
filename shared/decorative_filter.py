import re
import logging
from collections import defaultdict
from hashlib import md5
from typing import Tuple, Dict, Any

logger = logging.getLogger(__name__)

# Decorative image detection heuristics
ENABLE_SIZE_CHECK = False
ENABLE_KEYWORD_CHECK = False
ENABLE_FLAG_CHECK = False
ENABLE_CORNER_CHECK = False
ENABLE_DUPLICATE_CHECK = False

def get_image_hash(image_bytes: bytes) -> str:
    """Generate MD5 hash of image bytes."""
    return md5(image_bytes).hexdigest()

def is_force_decorative_by_filename(filename: str, config: Dict[str, Any]) -> bool:
    """
    Returns True if the filename matches a decorative rule in the config.
    
    Args:
        filename: The image filename to check
        config: Configuration dictionary with decorative_overrides
        
    Returns:
        bool: True if image should be forced decorative, False otherwise
    """
    try:
        # Get decorative rules from config
        decorative_overrides = config.get("decorative_overrides", {})
        rules = decorative_overrides.get("decorative_rules", {})
        contains_list = rules.get("contains", [])
        exact_list = rules.get("exact", [])
        
        # Also check legacy force_decorative for backwards compatibility
        legacy_force = decorative_overrides.get("force_decorative", [])
        
        # Get never decorative list
        never_list = decorative_overrides.get("never_decorative", [])
        
        filename_lower = filename.lower()

        # Explicit never-decorative overrides (highest priority)
        for never in never_list:
            if never.lower() in filename_lower:
                logger.debug(f"[Decorative ✗] Never decorative override: {filename} contains '{never}'")
                return False

        # Exact match check
        for exact in exact_list:
            if filename_lower == exact.lower():
                logger.info(f"[Decorative ✓] Exact match: {filename}")
                return True

        # Substring match check (both new and legacy)
        all_contains = list(set(contains_list + legacy_force))  # Combine and dedupe
        for partial in all_contains:
            if partial.lower() in filename_lower:
                logger.info(
                    f"[Decorative ✓] Partial match: {filename} contains '{partial}'"
                )
                return True

        return False

    except Exception as e:
        logger.error(f"[Decorative ✗] Error checking decorative status: {e}")
        return False


def is_force_decorative_by_filename_or_name(
    image_filename: str,
    shape_name: str,
    config: Dict[str, Any],
) -> bool:
    """Return True if filename or shape name matches force-decorative keywords."""

    rules = config.get("decorative_overrides", {}).get("force_decorative", [])
    scope = (
        config.get("decorative_overrides", {})
        .get("force_decorative_scope", "both")
        .lower()
    )

    image_filename = image_filename.lower() if image_filename else ""
    shape_name = shape_name.lower() if shape_name else ""

    if scope == "shape_name":
        return any(term in shape_name for term in rules)
    elif scope == "filename":
        return any(term in image_filename for term in rules)
    else:  # both
        return any(term in image_filename or term in shape_name for term in rules)

def is_decorative_image(
    image_bytes: bytes,
    image_name: str,
    position: Tuple[int, int],
    dimensions: Tuple[int, int],
    slide_shapes: list,
    image_hash: str,
    image_tracker: defaultdict
) -> Tuple[bool, list]:
    """
    Check if an image should be considered decorative based on heuristics.
    
    Args:
        image_bytes: Raw image data
        image_name: Image filename or shape name
        position: (x, y) position on slide
        dimensions: (width, height) of image
        slide_shapes: List of all shapes on the slide
        image_hash: MD5 hash of the image
        image_tracker: Dictionary tracking image occurrences
        
    Returns:
        Tuple of (is_decorative, notes_list)
    """
    notes = []
    is_decorative = False
    width, height = dimensions
    x, y = position

    # Size check
    if ENABLE_SIZE_CHECK:
        if width < 100 or height < 100:
            notes.append("Image too small")
            is_decorative = True
            logger.debug(f"Size check triggered for {image_name}: {width}x{height}")
            
        if width / height > 6 or height / width > 6:
            ratio = round(max(width/height, height/width), 1)
            notes.append(f"Extreme aspect ratio ({ratio}:1)")
            is_decorative = True
            logger.debug(f"Aspect ratio check triggered for {image_name}: {ratio}:1")

    # Keyword check
    if ENABLE_KEYWORD_CHECK:
        keywords = r'(logo|arrow|line|box|divider|underline|background|banner)'
        if re.search(keywords, image_name, re.IGNORECASE):
            notes.append("Filename suggests decoration")
            is_decorative = True
            logger.debug(f"Keyword check triggered for {image_name}")

    # Flag check
    if ENABLE_FLAG_CHECK and 'flag' in image_name.lower():
        notes.append("Contains the word 'flag'")
        is_decorative = True
        logger.debug(f"Flag check triggered for {image_name}")

    # Corner placement check
    if ENABLE_CORNER_CHECK:
        corner_threshold = 50
        slide_width_threshold = 600
        slide_height_threshold = 500
        
        if x < corner_threshold and y < corner_threshold:
            notes.append("Top-left corner")
            is_decorative = True
        elif x < corner_threshold and y > slide_height_threshold:
            notes.append("Bottom-left corner")
            is_decorative = True
        elif x > slide_width_threshold and y < corner_threshold:
            notes.append("Top-right corner")
            is_decorative = True
        elif x > slide_width_threshold and y > slide_height_threshold:
            notes.append("Bottom-right corner")
            is_decorative = True
            
        if is_decorative:
            logger.debug(f"Corner check triggered for {image_name} at position ({x}, {y})")

    # Duplicate check
    if ENABLE_DUPLICATE_CHECK:
        if image_hash and len(image_tracker[image_hash]) > 1:
            occurrence_count = len(image_tracker[image_hash])
            notes.append(f"Appears on {occurrence_count} slides")
            is_decorative = True
            logger.debug(f"Duplicate check triggered for {image_name}: appears {occurrence_count} times")

    # Log the final decision
    if is_decorative:
        logger.info(f"Image marked as decorative: {image_name} - Reasons: {', '.join(notes)}")
    else:
        logger.debug(f"Image not decorative: {image_name}")

    return is_decorative, notes


def validate_decorative_config(config: Dict[str, Any]) -> bool:
    """
    Validate that the decorative configuration is properly structured.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        bool: True if valid, False otherwise
    """
    try:
        decorative_overrides = config.get("decorative_overrides", {})
        
        # Check for required keys
        if "decorative_rules" not in decorative_overrides:
            logger.warning("Missing 'decorative_rules' in decorative_overrides")
            return False
            
        rules = decorative_overrides["decorative_rules"]
        if not isinstance(rules, dict):
            logger.warning("'decorative_rules' must be a dictionary")
            return False
            
        # Check for contains and exact lists
        if "contains" not in rules or not isinstance(rules["contains"], list):
            logger.warning("Missing or invalid 'contains' list in decorative_rules")
            return False
            
        if "exact" not in rules or not isinstance(rules["exact"], list):
            logger.warning("Missing or invalid 'exact' list in decorative_rules")
            return False
            
        # Check for never_decorative list
        if "never_decorative" not in decorative_overrides:
            logger.warning("Missing 'never_decorative' in decorative_overrides")
            return False
            
        return True
        
    except Exception as e:
        logger.error(f"Error validating decorative config: {e}")
        return False


# Testing and debug utilities
if __name__ == "__main__":
    # Set up logging for testing
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Test configuration
    test_config = {
        "decorative_overrides": {
            "decorative_rules": {
                "contains": ["logo", "watermark", "border"],
                "exact": ["utsw_logo.png", "footer.jpg"]
            },
            "force_decorative": ["divider", "separator"],
            "never_decorative": ["anatomy", "xray", "mri"]
        }
    }
    
    # Validate config
    print("Config validation:", validate_decorative_config(test_config))
    
    # Test filename checks
    test_files = [
        "utsw_logo.png",       # Should be decorative (exact match)
        "header_logo.jpg",     # Should be decorative (contains "logo")
        "anatomy_chart.png",   # Should NOT be decorative (never list)
        "xray_chest.jpg",      # Should NOT be decorative (never list)
        "divider_line.png",    # Should be decorative (legacy list)
        "random_image.jpg"     # Should NOT be decorative
    ]
    
    print("\nFilename decorative checks:")
    for filename in test_files:
        result = is_force_decorative_by_filename(filename, test_config)
        print(f"  {filename}: {'Decorative' if result else 'Not decorative'}")
    
    # Test heuristic flags
    print("\nHeuristic flag status:")
    print(f"  Size check: {'ENABLED' if ENABLE_SIZE_CHECK else 'DISABLED'}")
    print(f"  Keyword check: {'ENABLED' if ENABLE_KEYWORD_CHECK else 'DISABLED'}")
    print(f"  Flag check: {'ENABLED' if ENABLE_FLAG_CHECK else 'DISABLED'}")
    print(f"  Corner check: {'ENABLED' if ENABLE_CORNER_CHECK else 'DISABLED'}")
    print(f"  Duplicate check: {'ENABLED' if ENABLE_DUPLICATE_CHECK else 'DISABLED'}")