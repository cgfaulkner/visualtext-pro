"""
LLaVA image path validation and thumbnail-to-normalized conversion.

Single module for the conversion-first gate: path validation uses resolved
containment and exact path segment rules only (no substring matching).
Conversion writes to temp with UUID filename and atomic rename; converted
files are under temp_folder and covered by existing temp cleanup.
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Optional, Sequence, Tuple, Union

logger = logging.getLogger(__name__)


def _resolve_path(p: Union[str, Path]) -> Path:
    """Resolve to absolute path; symlinks are followed by resolve()."""
    return Path(p).resolve()


def _is_contained_in(resolved: Path, parent: Path) -> bool:
    """True if resolved is under parent (resolved). No substring matching."""
    try:
        parent_resolved = Path(parent).resolve()
        resolved.relative_to(parent_resolved)
        return True
    except ValueError:
        return False


def _has_exact_segment_thumbs(resolved: Path) -> bool:
    """True if any path segment equals exactly 'thumbs' (not substring)."""
    return "thumbs" in resolved.parts


def validate_llava_image_path(
    image_path: Union[str, Path],
    config_manager,  # ConfigManager
    *,
    allowed_extra_dirs: Optional[Sequence[Path]] = None,
) -> Tuple[bool, str]:
    """
    Validate that image_path is allowed for LLaVA (normalized) or is a thumbnail.

    Containment uses Path.resolve() and relative containment only; no substring
    matching. Rejection: path under configured thumbnail folder and/or exact
    path segment "thumbs". Allowed: path under temp_folder, system temp, or
    allowed_extra_dirs. Secondary fallback: path under a directory with segment
    "crops".

    Returns:
        (allowed, source_label): source_label in ("normalized", "thumbnail", "unknown").
    """
    if not image_path or not str(image_path).strip():
        return (False, "unknown")
    try:
        resolved = _resolve_path(image_path)
    except (OSError, RuntimeError) as e:
        logger.debug("Path resolution failed for %s: %s", image_path, e)
        return (False, "unknown")

    # Rejection: under configured thumbnail folder (resolved)
    try:
        thumb_folder = Path(config_manager.get_thumbnail_folder()).resolve()
        if _is_contained_in(resolved, thumb_folder):
            return (False, "thumbnail")
    except (OSError, RuntimeError):
        pass

    # Rejection: exact path segment "thumbs"
    if _has_exact_segment_thumbs(resolved):
        return (False, "thumbnail")

    # Allowed: under configured temp_folder
    try:
        temp_folder = Path(config_manager.get_temp_folder()).resolve()
        if _is_contained_in(resolved, temp_folder):
            return (True, "normalized")
    except (OSError, RuntimeError):
        pass

    # Allowed: under system temp
    try:
        system_temp = Path(tempfile.gettempdir()).resolve()
        if _is_contained_in(resolved, system_temp):
            return (True, "normalized")
    except (OSError, RuntimeError):
        pass

    # Allowed: under allowed_extra_dirs (e.g. run crops_dir)
    if allowed_extra_dirs:
        for d in allowed_extra_dirs:
            try:
                if _is_contained_in(resolved, Path(d).resolve()):
                    return (True, "normalized")
            except (OSError, RuntimeError):
                continue

    # Secondary fallback: path has segment "crops" (e.g. run_dir/crops/...)
    if "crops" in resolved.parts:
        return (True, "normalized")

    return (False, "unknown")


def convert_thumbnail_to_normalized(
    thumbnail_path: Union[str, Path],
    config_manager,  # ConfigManager
    *,
    temp_base: Optional[Path] = None,
    min_normalized_width: int = 512,
    require_min_width: bool = False,
) -> Tuple[Optional[Path], Optional[str], bool]:
    """
    Convert thumbnail image to a normalized image file under temp for LLaVA.

    When PIL is available: enforces min_normalized_width (upscales if needed).
    When PIL is unavailable: if require_min_width is True, fails with a clear
    error; otherwise writes raw bytes and returns width_enforced=False (caller
    should warn and set metadata flag).

    Returns:
        (normalized_path, error_message, width_enforced). On success error_message
        is None. width_enforced is True only when min_normalized_width was
        actually enforced (PIL path); False when PIL was missing or not used.
    """
    path = Path(thumbnail_path)
    if not path.exists():
        return (None, f"Thumbnail file not found: {path}", False)
    base_dir = temp_base
    if base_dir is None:
        base_dir = Path(config_manager.get_temp_folder()).resolve()
    base_dir = Path(base_dir).resolve()
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError) as e:
        logger.warning("Permission denied creating temp dir for conversion: %s", e)
        return (None, f"Permission denied: {e}", False)

    try:
        from PIL import Image
    except ImportError:
        if require_min_width:
            return (
                None,
                "PIL (Pillow) is required to enforce min_normalized_width for LLaVA "
                "input. Install Pillow or use pre-normalized images under crops/.",
                False,
            )
        logger.warning(
            "PIL unavailable; normalized width could not be enforced. "
            "Install Pillow for min_normalized_width guarantee."
        )
        try:
            data = path.read_bytes()
        except (OSError, PermissionError) as e:
            logger.warning("Permission denied reading thumbnail: %s", e)
            return (None, f"Permission denied: {e}", False)
        final_name = f"llava_norm_{uuid.uuid4().hex}.png"
        final_path = base_dir / final_name
        temp_path = base_dir / f"{final_name}.tmp"
        try:
            temp_path.write_bytes(data)
            temp_path.replace(final_path)
            return (final_path, None, False)
        except (OSError, PermissionError) as e:
            logger.warning("Permission denied writing converted image: %s", e)
            if temp_path.exists():
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass
            return (None, f"Permission denied: {e}", False)

    try:
        img = Image.open(path).copy()
        img.load()
    except (OSError, PermissionError) as e:
        logger.warning("Permission denied reading thumbnail: %s", e)
        return (None, f"Permission denied: {e}", False)
    except Exception as e:
        logger.warning("Could not open thumbnail image: %s", e)
        return (None, str(e), False)

    # Preserve or produce dimensions suitable for LLaVA (min_normalized_width)
    w, h = img.size
    if w < min_normalized_width and min_normalized_width > 0:
        scale = min_normalized_width / w
        new_w = min_normalized_width
        new_h = max(1, int(round(h * scale)))
        img = img.resize((new_w, new_h), getattr(Image, "Resampling", Image).LANCZOS)
        logger.debug("Upscaled thumbnail from %sx%s to %sx%s for LLaVA", w, h, new_w, new_h)

    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    final_name = f"llava_norm_{uuid.uuid4().hex}.png"
    final_path = base_dir / final_name
    temp_path = base_dir / f"{final_name}.tmp"
    try:
        img.save(temp_path, "PNG")
        try:
            f = temp_path.open("rb")
            f.flush()
            if hasattr(f, "fileno") and hasattr(os, "fsync"):
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
            f.close()
        except Exception:
            pass
        temp_path.replace(final_path)
        return (final_path, None, True)
    except (OSError, PermissionError) as e:
        logger.warning("Permission denied writing converted image: %s", e)
        if temp_path.exists():
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
        return (None, f"Permission denied: {e}", False)
    except Exception as e:
        logger.warning("Could not save converted image: %s", e)
        if temp_path.exists():
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
        return (None, str(e), False)
