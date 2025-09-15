"""
Perceptual hash implementation for cross-format image deduplication.
Provides aHash (average hash) for stable image fingerprinting across formats.
"""

import hashlib
import logging
from typing import Optional, List, Union
from pathlib import Path

logger = logging.getLogger(__name__)


def ahash_key(pil_img, hash_size: int = 8) -> str:
    """
    Compute average hash (aHash) of a PIL Image.
    
    This creates a perceptual fingerprint that remains stable across:
    - Format conversions (WMF→PNG, JPG→PNG, etc.)
    - Minor compression changes
    - Slight scaling variations
    
    Args:
        pil_img: PIL Image object
        hash_size: Hash grid size (8x8 = 64 bits typical)
        
    Returns:
        Hex string representation of perceptual hash
    """
    try:
        # Convert to grayscale and resize to hash_size x hash_size
        img = pil_img.convert("L").resize((hash_size, hash_size), resample=1)  # LANCZOS
        
        # Get pixel values as flat array
        import numpy as np
        pixels = np.array(img).flatten()
        
        # Compute average pixel value
        avg = pixels.mean()
        
        # Create binary hash: 1 if pixel > average, 0 otherwise
        binary_hash = (pixels > avg).astype(np.uint8)
        
        # Convert binary array to hex string
        # Pack bits into bytes for compact representation
        hash_bits = ''.join(map(str, binary_hash))
        
        # Convert binary string to integer then to hex
        hash_int = int(hash_bits, 2) if hash_bits else 0
        hash_hex = hex(hash_int)[2:].zfill((hash_size * hash_size + 3) // 4)
        
        return f"ahash:{hash_hex}"
        
    except Exception as e:
        logger.warning(f"Failed to compute perceptual hash: {e}")
        return f"ahash:error"


def dhash_key(pil_img, hash_size: int = 8) -> str:
    """
    Compute difference hash (dHash) of a PIL Image.
    
    More robust to brightness variations than aHash.
    Compares adjacent pixels rather than average.
    
    Args:
        pil_img: PIL Image object  
        hash_size: Hash grid size
        
    Returns:
        Hex string representation of perceptual hash
    """
    try:
        # Convert to grayscale, resize to hash_size x (hash_size + 1) for horizontal differences
        img = pil_img.convert("L").resize((hash_size + 1, hash_size), resample=1)
        
        import numpy as np
        pixels = np.array(img)
        
        # Compute differences between adjacent horizontal pixels
        diff = pixels[:, 1:] > pixels[:, :-1]
        
        # Flatten to binary array
        binary_hash = diff.flatten().astype(np.uint8)
        
        # Convert to hex
        hash_bits = ''.join(map(str, binary_hash))
        hash_int = int(hash_bits, 2) if hash_bits else 0
        hash_hex = hex(hash_int)[2:].zfill((hash_size * hash_size + 3) // 4)
        
        return f"dhash:{hash_hex}"
        
    except Exception as e:
        logger.warning(f"Failed to compute difference hash: {e}")
        return f"dhash:error"


def build_cache_keys(image_bytes: bytes, pil_thumbnail: Optional[object] = None, 
                    metadata: Optional[dict] = None) -> List[str]:
    """
    Build comprehensive cache key set for cross-format deduplication.
    
    Creates multiple keys to maximize hit rate across different scenarios:
    1. Byte hash (exact matches)
    2. Perceptual hashes (format-independent matches)
    3. Content-based keys (slide+shape position)
    
    Args:
        image_bytes: Raw image data
        pil_thumbnail: Optional PIL Image for perceptual hashing
        metadata: Optional metadata dict with slide_idx, shape_id, dimensions
        
    Returns:
        List of cache keys to try for lookups
    """
    keys = []
    
    # Always include byte-based hash for exact matches
    if image_bytes:
        byte_hash = hashlib.sha1(image_bytes).hexdigest()
        keys.append(f"bytesha1:{byte_hash}")
    
    # Add perceptual hashes if thumbnail available
    if pil_thumbnail is not None:
        try:
            # Primary perceptual hash
            ahash = ahash_key(pil_thumbnail)
            keys.append(ahash)
            
            # Secondary hash for robustness
            dhash = dhash_key(pil_thumbnail)
            keys.append(dhash)
            
        except Exception as e:
            logger.debug(f"Error computing perceptual hashes: {e}")
    
    # Add content-based key for positional matches
    if metadata:
        try:
            slide_idx = metadata.get('slide_idx', 0)
            shape_id = metadata.get('shape_id', 0) 
            width = metadata.get('w', metadata.get('width', 0))
            height = metadata.get('h', metadata.get('height', 0))
            
            # Create position+size based key (useful for identical layouts)
            content_key = f"content:slide{slide_idx}-shape{shape_id}-{width}x{height}"
            keys.append(content_key)
            
        except Exception as e:
            logger.debug(f"Error creating content-based key: {e}")
    
    return keys


def hamming_distance(hash1: str, hash2: str) -> Optional[int]:
    """
    Compute Hamming distance between two hex hash strings.
    
    Used for perceptual hash similarity detection.
    Lower distance = more similar images.
    
    Args:
        hash1: First hash string (with prefix like "ahash:")
        hash2: Second hash string (with prefix)
        
    Returns:
        Hamming distance, or None if hashes incompatible
    """
    try:
        # Extract hash type and hex value
        if ':' not in hash1 or ':' not in hash2:
            return None
            
        type1, hex1 = hash1.split(':', 1)
        type2, hex2 = hash2.split(':', 1)
        
        # Only compare same hash types
        if type1 != type2:
            return None
        
        # Convert hex to binary for bit comparison
        try:
            int1 = int(hex1, 16)
            int2 = int(hex2, 16)
        except ValueError:
            return None
        
        # XOR and count set bits
        xor = int1 ^ int2
        distance = bin(xor).count('1')
        
        return distance
        
    except Exception as e:
        logger.debug(f"Error computing Hamming distance: {e}")
        return None


def are_similar_images(hash1: str, hash2: str, threshold: int = 5) -> bool:
    """
    Determine if two perceptual hashes represent similar images.
    
    Args:
        hash1: First perceptual hash
        hash2: Second perceptual hash  
        threshold: Maximum Hamming distance for similarity (default 5)
        
    Returns:
        True if images are likely similar
    """
    distance = hamming_distance(hash1, hash2)
    return distance is not None and distance <= threshold


def load_pil_image_safely(image_data: Union[bytes, str, Path]) -> Optional[object]:
    """
    Safely load image data into PIL Image object.
    
    Args:
        image_data: Image bytes, file path, or base64 string
        
    Returns:
        PIL Image object or None if loading fails
    """
    try:
        from PIL import Image
        import io
        import base64
        
        if isinstance(image_data, bytes):
            # Direct bytes
            return Image.open(io.BytesIO(image_data))
            
        elif isinstance(image_data, (str, Path)):
            path = Path(image_data)
            if path.exists():
                # File path
                return Image.open(path)
            else:
                # Try as base64 string
                try:
                    decoded = base64.b64decode(image_data, validate=True)
                    return Image.open(io.BytesIO(decoded))
                except Exception:
                    return None
        
        return None
        
    except Exception as e:
        logger.debug(f"Error loading image for perceptual hashing: {e}")
        return None