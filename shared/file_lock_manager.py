#!/usr/bin/env python3
"""
File Lock Manager
=================

Cross-platform file locking to prevent concurrent access corruption.

Supports:
- Unix/Linux/Mac: fcntl.flock()
- Windows: msvcrt.locking()
- Context manager for automatic release
- Timeout and retry logic
- Stale lock detection

Usage:
    from shared.file_lock_manager import FileLock, LockError

    # Context manager (recommended)
    with FileLock(file_path, timeout=30.0) as lock:
        # Process file safely
        pass

    # Manual lock management
    lock = FileLock(file_path)
    try:
        if lock.acquire(blocking=True):
            # Process file
            pass
    finally:
        lock.release()
"""

import logging
import os
import platform
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class LockError(Exception):
    """
    Exception raised when file locking fails.

    Attributes:
        file_path: Path to the file that couldn't be locked
        reason: Description of why locking failed
    """
    def __init__(self, message: str, file_path: Optional[Path] = None):
        self.file_path = file_path
        super().__init__(message)


class FileLock:
    """
    Cross-platform file locking mechanism.

    Prevents concurrent access to files by multiple processes.
    Supports both blocking and non-blocking modes with timeout.

    Attributes:
        file_path: Path to the file to lock
        timeout: Maximum time to wait for lock acquisition (seconds)
        poll_interval: How often to check for lock availability (seconds)
    """

    def __init__(self, file_path: Path, timeout: float = 30.0, poll_interval: float = 0.5):
        """
        Initialize file lock.

        Args:
            file_path: Path to the file to lock
            timeout: Maximum time to wait for lock (default: 30 seconds)
            poll_interval: Polling interval for lock checks (default: 0.5 seconds)
        """
        self.file_path = Path(file_path)
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.lock_file_path = self._get_lock_file_path()
        self._lock_fd = None
        self._is_locked = False
        self._platform = platform.system()

    def _get_lock_file_path(self) -> Path:
        """Get path to the lock file."""
        return self.file_path.parent / f"{self.file_path.name}.lock"

    def acquire(self, blocking: bool = True) -> bool:
        """
        Acquire lock on the file.

        Args:
            blocking: If True, wait up to timeout for lock. If False, return immediately.

        Returns:
            True if lock acquired, False otherwise

        Raises:
            LockError: If lock cannot be acquired after timeout (only in blocking mode)
        """
        if self._is_locked:
            logger.warning(f"Lock already held on {self.file_path}")
            return True

        start_time = time.time()

        while True:
            try:
                # Create lock file if it doesn't exist
                self.lock_file_path.parent.mkdir(parents=True, exist_ok=True)

                # Open lock file
                if self._platform == 'Windows':
                    self._lock_fd = os.open(
                        str(self.lock_file_path),
                        os.O_WRONLY | os.O_CREAT | os.O_TRUNC
                    )
                    # Try to lock on Windows
                    import msvcrt
                    msvcrt.locking(self._lock_fd, msvcrt.LK_NBLCK, 1)
                else:
                    # Unix/Linux/Mac
                    self._lock_fd = os.open(
                        str(self.lock_file_path),
                        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                        0o644
                    )
                    # Try to lock on Unix
                    import fcntl
                    fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

                # Write PID to lock file for debugging
                os.write(self._lock_fd, str(os.getpid()).encode())
                os.fsync(self._lock_fd)

                self._is_locked = True
                logger.debug(f"Acquired lock on {self.file_path}")
                return True

            except (IOError, OSError) as e:
                # Lock is held by another process
                if not blocking:
                    self._cleanup_failed_lock()
                    return False

                # Check timeout
                elapsed = time.time() - start_time
                if elapsed >= self.timeout:
                    self._cleanup_failed_lock()
                    error_msg = f"Timeout waiting for lock on {self.file_path} after {elapsed:.1f}s"
                    logger.error(error_msg)
                    raise LockError(error_msg, self.file_path)

                # Wait and retry
                time.sleep(self.poll_interval)

            except Exception as e:
                self._cleanup_failed_lock()
                error_msg = f"Unexpected error acquiring lock on {self.file_path}: {e}"
                logger.error(error_msg)
                raise LockError(error_msg, self.file_path)

    def release(self) -> None:
        """
        Release the lock.

        Safe to call multiple times. Handles already-released locks gracefully.
        """
        if not self._is_locked:
            return

        try:
            if self._lock_fd is not None:
                # Release the lock
                if self._platform == 'Windows':
                    import msvcrt
                    try:
                        msvcrt.locking(self._lock_fd, msvcrt.LK_UNLCK, 1)
                    except:
                        pass  # May already be unlocked
                else:
                    import fcntl
                    try:
                        fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                    except:
                        pass  # May already be unlocked

                # Close file descriptor
                try:
                    os.close(self._lock_fd)
                except:
                    pass

                self._lock_fd = None

            # Remove lock file
            try:
                if self.lock_file_path.exists():
                    self.lock_file_path.unlink()
            except Exception as e:
                logger.warning(f"Could not remove lock file {self.lock_file_path}: {e}")

            self._is_locked = False
            logger.debug(f"Released lock on {self.file_path}")

        except Exception as e:
            logger.error(f"Error releasing lock on {self.file_path}: {e}")

    def _cleanup_failed_lock(self) -> None:
        """Clean up after failed lock acquisition."""
        if self._lock_fd is not None:
            try:
                os.close(self._lock_fd)
            except:
                pass
            self._lock_fd = None

    def is_locked(self) -> bool:
        """
        Check if this lock instance currently holds the lock.

        Returns:
            True if lock is held by this instance
        """
        return self._is_locked

    def __enter__(self) -> 'FileLock':
        """Enter context manager - acquire lock."""
        self.acquire(blocking=True)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager - release lock."""
        self.release()
        return None

    def __del__(self):
        """Ensure lock is released when object is destroyed."""
        try:
            self.release()
        except:
            pass


def create_lock_file(path: Path) -> Path:
    """
    Create a lock file path for the given file.

    Args:
        path: Path to the file to lock

    Returns:
        Path to the lock file
    """
    return path.parent / f"{path.name}.lock"


def is_file_locked(path: Path) -> bool:
    """
    Check if a file is currently locked (non-blocking check).

    Args:
        path: Path to the file to check

    Returns:
        True if file appears to be locked
    """
    lock_file = create_lock_file(path)

    if not lock_file.exists():
        return False

    # Try to acquire lock non-blocking
    lock = FileLock(path, timeout=0.0)
    try:
        if lock.acquire(blocking=False):
            lock.release()
            return False
        return True
    except:
        return True


def wait_for_lock_release(path: Path, timeout: float = 60.0, poll_interval: float = 1.0) -> bool:
    """
    Wait for a file lock to be released.

    Args:
        path: Path to the file
        timeout: Maximum time to wait (seconds)
        poll_interval: How often to check (seconds)

    Returns:
        True if lock was released within timeout, False otherwise
    """
    start_time = time.time()

    while time.time() - start_time < timeout:
        if not is_file_locked(path):
            return True
        time.sleep(poll_interval)

    return False


def get_lock_holder_pid(path: Path) -> Optional[int]:
    """
    Get the PID of the process holding the lock.

    Args:
        path: Path to the file

    Returns:
        PID of lock holder, or None if not locked or PID unavailable
    """
    lock_file = create_lock_file(path)

    if not lock_file.exists():
        return None

    try:
        with open(lock_file, 'r') as f:
            pid_str = f.read().strip()
            return int(pid_str)
    except:
        return None


def is_process_running(pid: int) -> bool:
    """
    Check if a process with given PID is running.

    Args:
        pid: Process ID to check

    Returns:
        True if process is running
    """
    try:
        # Send signal 0 to check if process exists (Unix)
        # On Windows, use different approach
        if platform.system() == 'Windows':
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_INFORMATION = 0x0400
            handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, 0, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        else:
            # Unix: send signal 0 (doesn't actually send signal, just checks)
            os.kill(pid, 0)
            return True
    except (OSError, AttributeError):
        return False
