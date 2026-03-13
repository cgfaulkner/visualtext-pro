"""File fingerprint for batch resume. See docs/batch_completion_criteria.md."""

from pathlib import Path


def file_fingerprint(path: Path) -> str:
    """Return a stable fingerprint for the file (mtime + size). Empty string if missing."""
    try:
        stat = path.stat()
        return f"{stat.st_mtime_ns}_{stat.st_size}"
    except OSError:
        return ""
