#!/usr/bin/env python3
"""
Resource Management for VisualText Pro Processing
==========================================

Centralized resource cleanup and monitoring to prevent temp file leaks
and ensure safe operations with memory/disk validation.

Components:
- TempFileManager: Track and cleanup temp files
- ResourceMonitor: Memory/disk space validation
- ResourceContext: Context manager for safe operations
"""

import atexit
import logging
import os
import shutil
import tempfile
import threading
import weakref
import time
import signal
from pathlib import Path
from typing import Dict, List, Optional, Set, Any
from contextlib import contextmanager
import psutil

logger = logging.getLogger(__name__)


class TempFileManager:
    """
    Centralized temporary file tracking and cleanup.

    Tracks all temp files and directories created during processing
    and ensures they are cleaned up even if processes fail unexpectedly.
    """

    def __init__(self):
        self._temp_files: Set[Path] = set()
        self._temp_dirs: Set[Path] = set()
        self._lock = threading.Lock()
        self._registered_cleanup = False
        self._cleanup_timeout = 5.0  # 5 seconds max for cleanup
        self._is_exiting = False

        # Register cleanup on exit
        if not self._registered_cleanup:
            atexit.register(self._safe_cleanup_all)
            self._registered_cleanup = True

    def create_temp_file(self, suffix: str = "", prefix: str = "pdf_alt_",
                        dir: Optional[Path] = None, delete: bool = False) -> Path:
        """
        Create a temporary file and track it for cleanup.

        Args:
            suffix: File suffix (e.g., '.png', '.json')
            prefix: File prefix
            dir: Directory to create file in (default: system temp)
            delete: If True, file will be auto-deleted when closed

        Returns:
            Path to created temp file
        """
        if not self._try_acquire_lock():
            logger.warning("Lock timeout in create_temp_file")
            raise RuntimeError("Unable to acquire lock for temp file creation")

        try:
            fd, temp_path = tempfile.mkstemp(
                suffix=suffix,
                prefix=prefix,
                dir=str(dir) if dir else None
            )

            # Close the file descriptor if not auto-deleting
            if not delete:
                os.close(fd)

            temp_path = Path(temp_path)
            self._temp_files.add(temp_path)

            logger.debug(f"Created temp file: {temp_path}")
            return temp_path
        finally:
            try:
                self._lock.release()
            except Exception:
                pass

    def create_temp_dir(self, suffix: str = "", prefix: str = "pdf_alt_",
                       dir: Optional[Path] = None) -> Path:
        """
        Create a temporary directory and track it for cleanup.

        Args:
            suffix: Directory suffix
            prefix: Directory prefix
            dir: Parent directory (default: system temp)

        Returns:
            Path to created temp directory
        """
        if not self._try_acquire_lock():
            logger.warning("Lock timeout in create_temp_dir")
            raise RuntimeError("Unable to acquire lock for temp dir creation")

        try:
            temp_dir = tempfile.mkdtemp(
                suffix=suffix,
                prefix=prefix,
                dir=str(dir) if dir else None
            )

            temp_dir = Path(temp_dir)
            self._temp_dirs.add(temp_dir)

            logger.debug(f"Created temp dir: {temp_dir}")
            return temp_dir
        finally:
            try:
                self._lock.release()
            except Exception:
                pass

    def track_file(self, file_path: Path) -> Path:
        """
        Track an existing file for cleanup.

        Args:
            file_path: Path to file to track

        Returns:
            The same path (for chaining)
        """
        if not self._try_acquire_lock():
            logger.warning("Lock timeout in track_file")
            return Path(file_path)  # Return path even if we can't track it

        try:
            self._temp_files.add(Path(file_path))
            logger.debug(f"Tracking file: {file_path}")
            return Path(file_path)
        finally:
            try:
                self._lock.release()
            except Exception:
                pass

    def track_dir(self, dir_path: Path) -> Path:
        """
        Track an existing directory for cleanup.

        Args:
            dir_path: Path to directory to track

        Returns:
            The same path (for chaining)
        """
        if not self._try_acquire_lock():
            logger.warning("Lock timeout in track_dir")
            return Path(dir_path)  # Return path even if we can't track it

        try:
            self._temp_dirs.add(Path(dir_path))
            logger.debug(f"Tracking dir: {dir_path}")
            return Path(dir_path)
        finally:
            try:
                self._lock.release()
            except Exception:
                pass

    def _try_acquire_lock(self, timeout: float = 1.0) -> bool:
        """Try to acquire lock with timeout."""
        try:
            return self._lock.acquire(timeout=timeout)
        except Exception:
            return False

    def cleanup_file(self, file_path: Path, _skip_lock: bool = False) -> bool:
        """
        Clean up a specific temp file.

        Args:
            file_path: Path to file to clean up
            _skip_lock: Internal flag to skip lock acquisition (for internal use)

        Returns:
            True if file was successfully removed
        """
        if not _skip_lock:
            if not self._try_acquire_lock(timeout=self._cleanup_timeout):
                logger.warning(f"Lock timeout during file cleanup: {file_path}")
                return False

        try:
            file_path = Path(file_path)
            success = False

            try:
                if file_path.exists():
                    file_path.unlink()
                    logger.debug(f"Cleaned up temp file: {file_path}")
                    success = True
                self._temp_files.discard(file_path)
            except Exception as e:
                logger.warning(f"Failed to cleanup temp file {file_path}: {e}")

            return success
        finally:
            if not _skip_lock:
                try:
                    self._lock.release()
                except Exception:
                    pass

    def cleanup_dir(self, dir_path: Path, _skip_lock: bool = False) -> bool:
        """
        Clean up a specific temp directory.

        Args:
            dir_path: Path to directory to clean up
            _skip_lock: Internal flag to skip lock acquisition (for internal use)

        Returns:
            True if directory was successfully removed
        """
        if not _skip_lock:
            if not self._try_acquire_lock(timeout=self._cleanup_timeout):
                logger.warning(f"Lock timeout during dir cleanup: {dir_path}")
                return False

        try:
            dir_path = Path(dir_path)
            success = False

            try:
                if dir_path.exists():
                    shutil.rmtree(dir_path)
                    logger.debug(f"Cleaned up temp dir: {dir_path}")
                    success = True
                self._temp_dirs.discard(dir_path)
            except Exception as e:
                logger.warning(f"Failed to cleanup temp dir {dir_path}: {e}")

            return success
        finally:
            if not _skip_lock:
                try:
                    self._lock.release()
                except Exception:
                    pass

    def cleanup_all(self) -> Dict[str, int]:
        """
        Clean up all tracked temporary files and directories.

        Returns:
            Dictionary with cleanup statistics
        """
        if not self._try_acquire_lock(timeout=self._cleanup_timeout):
            logger.warning("Lock timeout during cleanup_all, attempting emergency cleanup")
            return self._emergency_cleanup()

        try:
            return self._cleanup_with_lock()
        finally:
            try:
                self._lock.release()
            except Exception:
                pass

    def _cleanup_with_lock(self) -> Dict[str, int]:
        """Internal cleanup method that assumes lock is already held."""
        files_cleaned = 0
        dirs_cleaned = 0
        files_failed = 0
        dirs_failed = 0
        start_time = time.time()

        # Clean up files with early exit check
        temp_files_copy = list(self._temp_files)
        for i, file_path in enumerate(temp_files_copy):
            # Early exit condition - check if we're taking too long or exiting
            if self._is_exiting and time.time() - start_time > 2.0:
                logger.warning(f"Early exit from file cleanup after {i}/{len(temp_files_copy)} files")
                break

            if self.cleanup_file(file_path, _skip_lock=True):
                files_cleaned += 1
            else:
                files_failed += 1

        # Clean up directories with early exit check
        temp_dirs_copy = list(self._temp_dirs)
        for i, dir_path in enumerate(temp_dirs_copy):
            # Early exit condition - check if we're taking too long or exiting
            if self._is_exiting and time.time() - start_time > 3.0:
                logger.warning(f"Early exit from dir cleanup after {i}/{len(temp_dirs_copy)} dirs")
                break

            if self.cleanup_dir(dir_path, _skip_lock=True):
                dirs_cleaned += 1
            else:
                dirs_failed += 1

        stats = {
            'files_cleaned': files_cleaned,
            'dirs_cleaned': dirs_cleaned,
            'files_failed': files_failed,
            'dirs_failed': dirs_failed,
            'total_cleaned': files_cleaned + dirs_cleaned,
            'total_failed': files_failed + dirs_failed
        }

        if stats['total_cleaned'] > 0:
            logger.info(f"Cleanup complete: {stats['total_cleaned']} items removed, {stats['total_failed']} failed")

        return stats

    def _emergency_cleanup(self) -> Dict[str, int]:
        """Emergency cleanup without locks for exit scenarios."""
        files_cleaned = 0
        dirs_cleaned = 0
        files_failed = 0
        dirs_failed = 0

        # Try to clean up files without lock
        try:
            temp_files_copy = list(self._temp_files) if hasattr(self, '_temp_files') else []
            for file_path in temp_files_copy[:10]:  # Limit to first 10 items for speed
                try:
                    file_path = Path(file_path)
                    if file_path.exists():
                        file_path.unlink()
                        files_cleaned += 1
                except Exception:
                    files_failed += 1
        except Exception:
            pass

        # Try to clean up directories without lock
        try:
            temp_dirs_copy = list(self._temp_dirs) if hasattr(self, '_temp_dirs') else []
            for dir_path in temp_dirs_copy[:5]:  # Limit to first 5 dirs for speed
                try:
                    dir_path = Path(dir_path)
                    if dir_path.exists():
                        shutil.rmtree(dir_path)
                        dirs_cleaned += 1
                except Exception:
                    dirs_failed += 1
        except Exception:
            pass

        logger.warning(f"Emergency cleanup completed: {files_cleaned + dirs_cleaned} items cleaned")
        return {
            'files_cleaned': files_cleaned,
            'dirs_cleaned': dirs_cleaned,
            'files_failed': files_failed,
            'dirs_failed': dirs_failed,
            'total_cleaned': files_cleaned + dirs_cleaned,
            'total_failed': files_failed + dirs_failed
        }

    def _safe_cleanup_all(self):
        """Safe cleanup method for atexit registration."""
        self._is_exiting = True
        try:
            # Set a signal handler for timeout
            def timeout_handler(signum, frame):
                logger.warning("Cleanup timeout reached, forcing exit")
                return

            old_handler = None
            try:
                old_handler = signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(int(self._cleanup_timeout))

                self.cleanup_all()

            except Exception as e:
                logger.warning(f"Exception during exit cleanup: {e}")
            finally:
                signal.alarm(0)  # Cancel alarm
                if old_handler is not None:
                    signal.signal(signal.SIGALRM, old_handler)

        except Exception as e:
            logger.warning(f"Failed to setup cleanup timeout: {e}")
            # Fallback to emergency cleanup
            self._emergency_cleanup()

    def get_tracked_count(self) -> Dict[str, int]:
        """
        Get count of currently tracked items.

        Returns:
            Dictionary with file and directory counts
        """
        if not self._try_acquire_lock():
            logger.warning("Lock timeout in get_tracked_count")
            return {'files': 0, 'dirs': 0, 'total': 0}

        try:
            return {
                'files': len(self._temp_files),
                'dirs': len(self._temp_dirs),
                'total': len(self._temp_files) + len(self._temp_dirs)
            }
        finally:
            try:
                self._lock.release()
            except Exception:
                pass


class ResourceMonitor:
    """
    System resource monitoring for memory and disk usage validation.

    Provides pre-flight checks to ensure sufficient resources are available
    before starting intensive operations.
    """

    def __init__(self, min_memory_mb: int = 500, min_disk_mb: int = 1000):
        """
        Initialize resource monitor.

        Args:
            min_memory_mb: Minimum available memory in MB
            min_disk_mb: Minimum available disk space in MB
        """
        self.min_memory_mb = min_memory_mb
        self.min_disk_mb = min_disk_mb

    def get_memory_info(self) -> Dict[str, float]:
        """
        Get current memory usage information.

        Returns:
            Dictionary with memory statistics in MB
        """
        try:
            memory = psutil.virtual_memory()
            return {
                'total_mb': memory.total / 1024 / 1024,
                'available_mb': memory.available / 1024 / 1024,
                'used_mb': memory.used / 1024 / 1024,
                'percent_used': memory.percent
            }
        except Exception as e:
            logger.warning(f"Failed to get memory info: {e}")
            return {
                'total_mb': 0,
                'available_mb': 0,
                'used_mb': 0,
                'percent_used': 0
            }

    def get_disk_info(self, path: Path = None) -> Dict[str, float]:
        """
        Get disk space information for a path.

        Args:
            path: Path to check disk space for (default: current working directory)

        Returns:
            Dictionary with disk statistics in MB
        """
        try:
            if path is None:
                path = Path.cwd()

            disk_usage = shutil.disk_usage(path)
            return {
                'total_mb': disk_usage.total / 1024 / 1024,
                'free_mb': disk_usage.free / 1024 / 1024,
                'used_mb': (disk_usage.total - disk_usage.free) / 1024 / 1024,
                'percent_used': ((disk_usage.total - disk_usage.free) / disk_usage.total) * 100
            }
        except Exception as e:
            logger.warning(f"Failed to get disk info for {path}: {e}")
            return {
                'total_mb': 0,
                'free_mb': 0,
                'used_mb': 0,
                'percent_used': 100
            }

    def check_memory_available(self, required_mb: Optional[int] = None) -> Dict[str, Any]:
        """
        Check if sufficient memory is available.

        Args:
            required_mb: Required memory in MB (default: use min_memory_mb)

        Returns:
            Dictionary with check results
        """
        required_mb = required_mb or self.min_memory_mb
        memory_info = self.get_memory_info()
        available_mb = memory_info['available_mb']

        sufficient = available_mb >= required_mb

        return {
            'sufficient': sufficient,
            'required_mb': required_mb,
            'available_mb': available_mb,
            'deficit_mb': max(0, required_mb - available_mb),
            'memory_info': memory_info
        }

    def check_disk_available(self, path: Path = None, required_mb: Optional[int] = None) -> Dict[str, Any]:
        """
        Check if sufficient disk space is available.

        Args:
            path: Path to check (default: current working directory)
            required_mb: Required disk space in MB (default: use min_disk_mb)

        Returns:
            Dictionary with check results
        """
        required_mb = required_mb or self.min_disk_mb
        disk_info = self.get_disk_info(path)
        free_mb = disk_info['free_mb']

        sufficient = free_mb >= required_mb

        return {
            'sufficient': sufficient,
            'required_mb': required_mb,
            'free_mb': free_mb,
            'deficit_mb': max(0, required_mb - free_mb),
            'path': str(path or Path.cwd()),
            'disk_info': disk_info
        }

    def validate_resources(self, required_memory_mb: Optional[int] = None,
                          required_disk_mb: Optional[int] = None,
                          disk_path: Path = None) -> Dict[str, Any]:
        """
        Validate that sufficient system resources are available.

        Args:
            required_memory_mb: Required memory in MB
            required_disk_mb: Required disk space in MB
            disk_path: Path to check disk space for

        Returns:
            Dictionary with validation results
        """
        memory_check = self.check_memory_available(required_memory_mb)
        disk_check = self.check_disk_available(disk_path, required_disk_mb)

        all_sufficient = memory_check['sufficient'] and disk_check['sufficient']

        result = {
            'sufficient': all_sufficient,
            'memory': memory_check,
            'disk': disk_check,
            'errors': []
        }

        if not memory_check['sufficient']:
            result['errors'].append(
                f"Insufficient memory: need {memory_check['required_mb']:.1f}MB, "
                f"have {memory_check['available_mb']:.1f}MB"
            )

        if not disk_check['sufficient']:
            result['errors'].append(
                f"Insufficient disk space: need {disk_check['required_mb']:.1f}MB, "
                f"have {disk_check['free_mb']:.1f}MB at {disk_check['path']}"
            )

        return result


@contextmanager
def ResourceContext(temp_file_manager: Optional[TempFileManager] = None,
                   resource_monitor: Optional[ResourceMonitor] = None,
                   validate_resources: bool = True,
                   required_memory_mb: Optional[int] = None,
                   required_disk_mb: Optional[int] = None,
                   cleanup_on_exit: bool = True):
    """
    Context manager for safe resource operations.

    Provides automatic temp file cleanup and optional resource validation.

    Args:
        temp_file_manager: TempFileManager instance (creates new if None)
        resource_monitor: ResourceMonitor instance (creates new if None)
        validate_resources: Whether to validate resources before starting
        required_memory_mb: Required memory in MB for validation
        required_disk_mb: Required disk space in MB for validation
        cleanup_on_exit: Whether to cleanup temp files on exit

    Yields:
        Tuple of (TempFileManager, ResourceMonitor)

    Raises:
        RuntimeError: If resource validation fails
    """
    # Create managers if not provided
    if temp_file_manager is None:
        temp_file_manager = TempFileManager()

    if resource_monitor is None:
        resource_monitor = ResourceMonitor()

    # Validate resources if requested
    if validate_resources:
        validation = resource_monitor.validate_resources(
            required_memory_mb=required_memory_mb,
            required_disk_mb=required_disk_mb
        )

        if not validation['sufficient']:
            error_msg = "Resource validation failed: " + "; ".join(validation['errors'])
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        logger.debug(f"Resource validation passed: "
                    f"{validation['memory']['available_mb']:.1f}MB memory, "
                    f"{validation['disk']['free_mb']:.1f}MB disk")

    # Track initial resource state
    initial_tracked = temp_file_manager.get_tracked_count()

    try:
        logger.debug("Entering resource context")
        yield temp_file_manager, resource_monitor

    except Exception as e:
        logger.error(f"Exception in resource context: {e}")
        raise

    finally:
        if cleanup_on_exit:
            # Clean up any temp files created during context
            final_tracked = temp_file_manager.get_tracked_count()
            items_created = final_tracked['total'] - initial_tracked['total']

            if items_created > 0:
                logger.debug(f"Cleaning up {items_created} temp items from context")
                cleanup_stats = temp_file_manager.cleanup_all()

                if cleanup_stats['total_failed'] > 0:
                    logger.warning(f"Failed to cleanup {cleanup_stats['total_failed']} temp items")

        logger.debug("Exiting resource context")


# Global singleton instances for convenience
_global_temp_manager: Optional[TempFileManager] = None
_global_resource_monitor: Optional[ResourceMonitor] = None


def get_temp_manager() -> TempFileManager:
    """Get global singleton TempFileManager instance."""
    global _global_temp_manager
    if _global_temp_manager is None:
        _global_temp_manager = TempFileManager()
    return _global_temp_manager


def get_resource_monitor() -> ResourceMonitor:
    """Get global singleton ResourceMonitor instance."""
    global _global_resource_monitor
    if _global_resource_monitor is None:
        _global_resource_monitor = ResourceMonitor()
    return _global_resource_monitor


def cleanup_all_temp_files() -> Dict[str, int]:
    """Cleanup all tracked temp files using global manager."""
    return get_temp_manager().cleanup_all()


def validate_system_resources(required_memory_mb: int = 500,
                             required_disk_mb: int = 1000) -> Dict[str, Any]:
    """Validate system resources using global monitor."""
    return get_resource_monitor().validate_resources(
        required_memory_mb=required_memory_mb,
        required_disk_mb=required_disk_mb
    )