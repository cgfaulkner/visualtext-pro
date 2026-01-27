"""
Path Validation and Sanitization Module

Provides security controls to prevent path traversal attacks and unauthorized
file system access. All user-provided paths should be validated through this
module before file operations.

Security Features:
- Prevents path traversal attacks (../, ~/, etc.)
- Validates paths stay within allowed directories
- Handles symlinks safely using Path.resolve()
- Logs security violations for audit trail
- Provides user-friendly error messages without exposing internal paths
"""

import logging
from pathlib import Path
from typing import Optional
import os

logger = logging.getLogger(__name__)


class SecurityError(Exception):
    """
    Custom exception for path validation failures.

    Raised when a user-provided path fails security validation,
    such as attempting path traversal or accessing unauthorized directories.
    """
    def __init__(self, message: str, attempted_path: Optional[str] = None):
        self.attempted_path = attempted_path
        super().__init__(message)


def get_project_root() -> Path:
    """
    Get the project root directory.

    Returns:
        Path: Absolute path to the project root directory
    """
    # Project root is parent of the 'shared' directory
    return Path(__file__).parent.parent.resolve()


def get_allowed_base_dirs() -> list[Path]:
    """
    Get list of allowed base directories for file operations.

    Returns:
        list[Path]: List of allowed base directory paths (resolved/absolute)
    """
    project_root = get_project_root()

    # project_root allows any path under repo; canonical runtime folders listed explicitly.
    # TODO: prefer loading allowed base dirs from config.yaml (see docs/cleanup-summary.md).
    allowed_dirs = [
        project_root,  # Allow entire project directory
        project_root / "documents_to_review",  # Canonical input folder
        project_root / "reviewed_reports",  # Canonical output folder
        project_root / "slide_thumbnails",  # Thumbnail folder
        project_root / "temp",  # Temp folder
        project_root / "archive",  # Archive (legacy code/outputs)
        project_root / "tests" / "fixtures",  # Test fixtures
    ]

    # Also allow system temp directory for temporary file operations
    try:
        import tempfile
        system_temp = Path(tempfile.gettempdir()).resolve()
        allowed_dirs.append(system_temp)
    except Exception as e:
        logger.warning(f"Could not add system temp directory to allowed paths: {e}")

    return [d.resolve() for d in allowed_dirs]


def is_safe_path(path: Path, base_dir: Optional[Path] = None) -> bool:
    """
    Check if a path is safe (within allowed directories).

    Uses Path.resolve() to handle symlinks and relative paths correctly.
    Checks the resolved path against allowed base directories.

    Args:
        path: Path to validate
        base_dir: Optional specific base directory to check against.
                 If None, checks against all allowed base directories.

    Returns:
        bool: True if path is safe, False otherwise
    """
    try:
        # Resolve to absolute path, following symlinks
        resolved_path = path.resolve()

        if base_dir is not None:
            # Check against specific base directory
            resolved_base = base_dir.resolve()
            try:
                resolved_path.relative_to(resolved_base)
                return True
            except ValueError:
                return False
        else:
            # Check against all allowed base directories
            allowed_dirs = get_allowed_base_dirs()
            for allowed_dir in allowed_dirs:
                try:
                    resolved_path.relative_to(allowed_dir)
                    return True
                except ValueError:
                    continue
            return False
    except (OSError, RuntimeError) as e:
        # Handle errors in path resolution (e.g., broken symlinks, permission issues)
        logger.warning(f"Error resolving path {path}: {e}")
        return False


def sanitize_input_path(user_path: str, allow_absolute: bool = False, base_dir: Optional[Path] = None) -> Path:
    """
    Sanitize and validate an input file path.

    Security checks:
    1. Converts to Path object and resolves to absolute form
    2. Checks for path traversal sequences (.., ~)
    3. Validates path stays within allowed directories
    4. Handles symlinks safely
    5. Raises SecurityError if validation fails

    Args:
        user_path: User-provided path string
        allow_absolute: If True, allows absolute paths. If False, rejects them.
        base_dir: Optional specific base directory to validate against.
                 If None, validates against all allowed directories.

    Returns:
        Path: Validated Path object (absolute, resolved)

    Raises:
        SecurityError: If path validation fails
        ValueError: If path is empty or invalid
    """
    if not user_path or not user_path.strip():
        raise ValueError("Path cannot be empty")

    user_path = user_path.strip()

    # Check for obviously suspicious patterns in the string
    suspicious_patterns = ['..', '~']
    for pattern in suspicious_patterns:
        if pattern in user_path:
            logger.warning(f"Path traversal attempt detected: {user_path}")
            raise SecurityError(
                "Invalid path: path traversal sequences are not allowed",
                attempted_path=user_path
            )

    # Convert to Path object
    try:
        path = Path(user_path)
    except Exception as e:
        raise ValueError(f"Invalid path format: {e}")

    # Check if absolute path (and whether that's allowed)
    if path.is_absolute() and not allow_absolute:
        logger.warning(f"Absolute path rejected: {user_path}")
        raise SecurityError(
            "Absolute paths are not allowed. Please use relative paths.",
            attempted_path=user_path
        )

    # If relative path, resolve it relative to project root or specified base
    if not path.is_absolute():
        if base_dir is not None:
            path = (base_dir / path).resolve()
        else:
            path = (get_project_root() / path).resolve()
    else:
        # Resolve absolute path (follows symlinks)
        path = path.resolve()

    # Validate path is within allowed directories
    if not is_safe_path(path, base_dir):
        logger.error(f"Path outside allowed directories: {user_path} -> {path}")
        raise SecurityError(
            "Access denied: path is outside allowed directories",
            attempted_path=user_path
        )

    logger.debug(f"Path validated: {user_path} -> {path}")
    return path


def validate_output_path(user_path: str, create_parents: bool = True, base_dir: Optional[Path] = None) -> Path:
    """
    Validate an output file path and optionally create parent directories.

    Similar to sanitize_input_path but for output files. Ensures:
    1. Path is within allowed directories
    2. Parent directory exists or can be created
    3. Path doesn't use traversal sequences

    Args:
        user_path: User-provided output path string
        create_parents: If True, creates parent directories if they don't exist
        base_dir: Optional specific base directory to validate against

    Returns:
        Path: Validated Path object (absolute, resolved)

    Raises:
        SecurityError: If path validation fails
        OSError: If parent directory creation fails
    """
    # Use same validation as input paths
    validated_path = sanitize_input_path(user_path, allow_absolute=False, base_dir=base_dir)

    # Ensure parent directory exists
    parent_dir = validated_path.parent
    if not parent_dir.exists():
        if create_parents:
            try:
                parent_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created output directory: {parent_dir}")
            except OSError as e:
                logger.error(f"Failed to create output directory {parent_dir}: {e}")
                raise SecurityError(
                    f"Cannot create output directory: {e}",
                    attempted_path=user_path
                )
        else:
            raise SecurityError(
                "Output directory does not exist and creation is disabled",
                attempted_path=user_path
            )

    return validated_path


def validate_glob_pattern(pattern: str, base_dir: Optional[Path] = None) -> tuple[Path, str]:
    """
    Validate a glob pattern for file discovery.

    Separates the base directory from the pattern and validates the base directory.
    Returns validated base directory and safe pattern.

    Args:
        pattern: Glob pattern (e.g., "input/*.pptx" or "**/*.pdf")
        base_dir: Optional base directory for the pattern

    Returns:
        tuple[Path, str]: (validated_base_dir, safe_pattern)

    Raises:
        SecurityError: If pattern attempts path traversal
    """
    # Check for traversal sequences in pattern
    if '..' in pattern or '~' in pattern:
        logger.warning(f"Path traversal in glob pattern: {pattern}")
        raise SecurityError(
            "Invalid glob pattern: path traversal sequences are not allowed",
            attempted_path=pattern
        )

    # Extract base directory from pattern
    pattern_path = Path(pattern)

    # Find the first part that isn't a wildcard
    parts = pattern_path.parts
    base_parts = []
    pattern_parts = []
    found_wildcard = False

    for part in parts:
        if '*' in part or '?' in part or '[' in part:
            found_wildcard = True
            pattern_parts.append(part)
        else:
            if found_wildcard:
                pattern_parts.append(part)
            else:
                base_parts.append(part)

    # Construct base directory and remaining pattern
    if base_parts:
        base_path = Path(*base_parts)
    else:
        base_path = Path('.')

    if pattern_parts:
        remaining_pattern = str(Path(*pattern_parts))
    else:
        remaining_pattern = '*'

    # Validate base directory
    if base_dir is not None:
        validated_base = sanitize_input_path(str(base_path), base_dir=base_dir)
    else:
        validated_base = sanitize_input_path(str(base_path))

    return validated_base, remaining_pattern


def validate_temp_path(filename: str) -> Path:
    """
    Create and validate a temporary file path.

    Creates path in project temp directory or system temp, ensuring it's safe.

    Args:
        filename: Desired temporary filename

    Returns:
        Path: Validated temporary file path

    Raises:
        SecurityError: If filename contains path traversal sequences
    """
    if '..' in filename or '/' in filename or '\\' in filename:
        raise SecurityError(
            "Invalid temporary filename: must not contain path separators",
            attempted_path=filename
        )

    project_root = get_project_root()
    temp_dir = project_root / "Temp"

    # Create temp directory if it doesn't exist
    if not temp_dir.exists():
        try:
            temp_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Fall back to system temp
            import tempfile
            temp_dir = Path(tempfile.gettempdir())

    temp_path = (temp_dir / filename).resolve()

    # Validate it's within allowed directories
    if not is_safe_path(temp_path):
        raise SecurityError(
            "Temporary path is outside allowed directories",
            attempted_path=filename
        )

    return temp_path
