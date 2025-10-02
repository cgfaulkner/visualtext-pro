#!/usr/bin/env python3
"""
Lock Monitor Utility
====================

Monitor and report on file locks in the system.

Provides utilities for:
- Listing locked files
- Checking lock age
- Detecting stale locks
- Cleaning up orphaned locks
"""

import logging
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from file_lock_manager import get_lock_holder_pid, is_process_running

logger = logging.getLogger(__name__)


def get_locked_files(directory: Path) -> List[Path]:
    """
    List all currently locked files in directory.

    Args:
        directory: Directory to search for lock files

    Returns:
        List of paths to files that appear to be locked
    """
    locked_files = []

    try:
        for lock_file in directory.rglob("*.lock"):
            # Get the original file path (remove .lock extension)
            original_file = lock_file.parent / lock_file.stem

            locked_files.append(original_file)

    except Exception as e:
        logger.error(f"Error scanning for locked files: {e}")

    return locked_files


def get_lock_age(lock_file: Path) -> float:
    """
    Return age of lock in seconds.

    Args:
        lock_file: Path to the .lock file

    Returns:
        Age in seconds, or 0 if file doesn't exist
    """
    if not lock_file.exists():
        return 0.0

    try:
        mtime = lock_file.stat().st_mtime
        return time.time() - mtime
    except Exception as e:
        logger.warning(f"Could not get lock age for {lock_file}: {e}")
        return 0.0


def is_lock_stale(lock_file: Path, threshold_hours: int = 1) -> bool:
    """
    Check if lock appears to be abandoned/stale.

    A lock is considered stale if:
    1. It's older than the threshold, AND
    2. The process that created it is no longer running

    Args:
        lock_file: Path to the .lock file
        threshold_hours: Age threshold in hours

    Returns:
        True if lock appears stale
    """
    if not lock_file.exists():
        return False

    # Check age
    age_seconds = get_lock_age(lock_file)
    if age_seconds < (threshold_hours * 3600):
        return False

    # Check if process is still running
    pid = get_lock_holder_pid(lock_file.parent / lock_file.stem)
    if pid is None:
        # Can't determine PID, consider stale if old enough
        return True

    # If process is dead, lock is stale
    return not is_process_running(pid)


def get_lock_info(lock_file: Path) -> Dict[str, Any]:
    """
    Get detailed information about a lock.

    Args:
        lock_file: Path to the .lock file

    Returns:
        Dict with lock information
    """
    info = {
        'lock_file': str(lock_file),
        'original_file': str(lock_file.parent / lock_file.stem),
        'exists': lock_file.exists(),
        'age_seconds': 0.0,
        'pid': None,
        'process_running': False,
        'is_stale': False
    }

    if not lock_file.exists():
        return info

    info['age_seconds'] = get_lock_age(lock_file)

    # Get PID
    original_file = lock_file.parent / lock_file.stem
    pid = get_lock_holder_pid(original_file)
    if pid:
        info['pid'] = pid
        info['process_running'] = is_process_running(pid)

    info['is_stale'] = is_lock_stale(lock_file)

    return info


def get_all_lock_info(directory: Path) -> List[Dict[str, Any]]:
    """
    Get information about all locks in directory.

    Args:
        directory: Directory to search

    Returns:
        List of lock info dicts
    """
    lock_infos = []

    try:
        for lock_file in directory.rglob("*.lock"):
            info = get_lock_info(lock_file)
            lock_infos.append(info)
    except Exception as e:
        logger.error(f"Error gathering lock info: {e}")

    return lock_infos


def format_lock_age(age_seconds: float) -> str:
    """
    Format lock age as human-readable string.

    Args:
        age_seconds: Age in seconds

    Returns:
        Formatted string like "2h 15m" or "45s"
    """
    if age_seconds < 60:
        return f"{int(age_seconds)}s"
    elif age_seconds < 3600:
        minutes = int(age_seconds / 60)
        seconds = int(age_seconds % 60)
        return f"{minutes}m {seconds}s"
    else:
        hours = int(age_seconds / 3600)
        minutes = int((age_seconds % 3600) / 60)
        return f"{hours}h {minutes}m"


def print_lock_status(directory: Path) -> None:
    """
    Print a formatted report of lock status.

    Args:
        directory: Directory to check
    """
    lock_infos = get_all_lock_info(directory)

    if not lock_infos:
        print("\n✅ No locked files found\n")
        return

    print(f"\n📋 Lock Status Report")
    print(f"Directory: {directory}")
    print(f"Found {len(lock_infos)} lock(s)\n")

    stale_count = sum(1 for info in lock_infos if info['is_stale'])
    if stale_count > 0:
        print(f"⚠️  {stale_count} stale lock(s) detected\n")

    print(f"{'File':<40} {'Age':<12} {'PID':<8} {'Status':<15}")
    print("-" * 80)

    for info in lock_infos:
        file_name = Path(info['original_file']).name
        age = format_lock_age(info['age_seconds'])
        pid = str(info['pid']) if info['pid'] else "unknown"

        if info['is_stale']:
            status = "⚠️  STALE"
        elif info['process_running']:
            status = "🔒 Active"
        else:
            status = "❓ Unknown"

        print(f"{file_name:<40} {age:<12} {pid:<8} {status:<15}")

    print()
